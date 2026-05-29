import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Union
from .base import BaseIngestionProcessor
from .utils import convert_unit, parse_date, split_billing_period
from ..models import FacilityProfile


class UtilityElectricityProcessor(BaseIngestionProcessor):
    """
    Utility Electricity data processor.
    Ingests portal CSVs, normalizes electricity units to kWh, sums peak and off-peak splits,
    infers missing start dates (30-day lookback), and splits usage across calendar month boundaries.
    """

    def get_ghg_scope(self) -> str:
        return "Scope 2"

    def get_activity_type(self) -> str:
        return "electricity"

    def parse_source(self, payload: Union[str, bytes]) -> List[Dict[str, Any]]:
        """
        Parses comma-separated CSV content.
        """
        decoded = payload if isinstance(payload, str) else payload.decode("utf-8")
        if decoded.startswith("\ufeff"):
            decoded = decoded[1:]

        reader = csv.DictReader(io.StringIO(decoded), delimiter=",")
        if reader.fieldnames:
            reader.fieldnames = [h.strip() for h in reader.fieldnames]

        return list(reader)

    def validate(self, raw_data: Dict[str, Any]) -> List[str]:
        issues: List[str] = []

        facility_name = raw_data.get("Facility_Name") or raw_data.get("Facility")
        if not facility_name:
            issues.append("Missing facility identification (Facility_Name).")

        end_date_str = raw_data.get("Billing_Period_End") or raw_data.get("End_Date")
        if not end_date_str:
            issues.append("Missing billing period end date.")

        # Check consumption metrics
        peak = raw_data.get("Peak_Usage_kWh")
        off_peak = raw_data.get("OffPeak_Usage_kWh")
        total_qty = raw_data.get("kWh_Consumed") or raw_data.get("Usage") or raw_data.get("Consumption")

        if not total_qty and not (peak or off_peak):
            issues.append("No consumption metrics found (kWh_Consumed or Peak/Off-Peak split).")

        return issues

    def normalize(self, raw_data: Dict[str, Any], organization_id: int) -> List[Dict[str, Any]]:
        warnings: List[str] = []

        # 1. Facility resolution
        raw_facility = raw_data.get("Facility_Name") or raw_data.get("Facility") or ""
        facility = FacilityProfile.objects.filter(
            organization_id=organization_id,
            facility_name__iexact=raw_facility.strip()
        ).first()

        if not facility and raw_facility:
            # Fallback check on plant_code
            facility = FacilityProfile.objects.filter(
                organization_id=organization_id,
                plant_code__iexact=raw_facility.strip()
            ).first()

        if not facility:
            warnings.append(f"Facility Profile '{raw_facility}' not found in organization.")

        # 2. Date parsing and inference
        raw_start_dt = raw_data.get("Billing_Period_Start") or raw_data.get("Start_Date") or ""
        raw_end_dt = raw_data.get("Billing_Period_End") or raw_data.get("End_Date") or ""

        parsed_end, end_warns = parse_date(raw_end_dt)
        warnings.extend(end_warns)

        parsed_start = None
        if raw_start_dt:
            parsed_start, start_warns = parse_date(raw_start_dt)
            warnings.extend(start_warns)
        elif parsed_end:
            # Inferred 30-day billing cycle lookback
            parsed_start = parsed_end - timedelta(days=30)
            warnings.append(f"Missing Billing_Period_Start. Inferred as 30 days prior ({parsed_start}).")

        # 3. Consumption accumulation & unit conversion
        raw_unit = raw_data.get("Unit") or raw_data.get("UoM") or "kWh"
        raw_cost_str = raw_data.get("Cost") or raw_data.get("Amount") or ""
        raw_currency = raw_data.get("Currency") or "EUR"

        # Check for peak/off-peak split
        raw_peak = raw_data.get("Peak_Usage_kWh")
        raw_off_peak = raw_data.get("OffPeak_Usage_kWh")
        
        consumption_decimal = Decimal("0.0")
        has_split_usage = False

        if raw_peak or raw_off_peak:
            # Parse peak
            peak_val = Decimal("0.0")
            if raw_peak and raw_peak != "INVALID":
                try:
                    peak_val = Decimal(str(raw_peak).strip().replace(",", "."))
                except (ValueError, TypeError, ArithmeticError):
                    warnings.append(f"Corrupted Peak Usage value '{raw_peak}', defaulted to 0.0.")
            
            # Parse off-peak
            off_peak_val = Decimal("0.0")
            if raw_off_peak and raw_off_peak != "INVALID":
                try:
                    off_peak_val = Decimal(str(raw_off_peak).strip().replace(",", "."))
                except (ValueError, TypeError, ArithmeticError):
                    warnings.append(f"Corrupted Off-Peak Usage value '{raw_off_peak}', defaulted to 0.0.")
            
            consumption_decimal = peak_val + off_peak_val
            has_split_usage = True
        else:
            # Parse total general consumption
            raw_total = raw_data.get("kWh_Consumed") or raw_data.get("Usage") or raw_data.get("Consumption") or "0.0"
            if raw_total and raw_total != "NA":
                try:
                    consumption_decimal = Decimal(str(raw_total).strip().replace(",", "."))
                except (ValueError, TypeError, ArithmeticError):
                    warnings.append(f"Corrupted consumption value '{raw_total}', defaulted to 0.0.")

        # Standardize consumption to kWh target
        norm_qty, norm_unit, unit_warns = convert_unit(consumption_decimal, raw_unit, default_target="kWh", field_label="consumption quantity")
        warnings.extend(unit_warns)

        # Parse cost
        cost_val = Decimal("0.0")
        if raw_cost_str:
            try:
                cost_val = Decimal(str(raw_cost_str).strip().replace(",", "."))
            except (ValueError, TypeError, ArithmeticError):
                warnings.append(f"Invalid cost format: '{raw_cost_str}'.")

        # Define metadata context
        metadata = {
            "peak_usage_kwh": str(raw_peak).strip() if raw_peak else None,
            "off_peak_usage_kwh": str(raw_off_peak).strip() if raw_off_peak else None,
            "has_split_usage": has_split_usage,
            "raw_billing_start": str(raw_start_dt).strip(),
            "raw_billing_end": str(raw_end_dt).strip(),
            "provider": str(raw_data.get("Provider") or "").strip()
        }

        # 4. Fractional date splitting logic
        if not parsed_start or not parsed_end:
            # If dates are missing, fallback to single un-split row with errors
            return [{
                "facility": facility,
                "start_date": parsed_start,
                "end_date": parsed_end,
                "quantity": norm_qty,
                "unit": norm_unit,
                "cost": cost_val,
                "currency": raw_currency,
                "validation_issues": warnings,
                "activity_metadata": metadata
            }]

        try:
            # Split the period fractionally across calendar months
            splits = split_billing_period(parsed_start, parsed_end, norm_qty)
            cost_splits = split_billing_period(parsed_start, parsed_end, cost_val)
            
            records = []
            for i, split in enumerate(splits):
                cost_split = cost_splits[i]["allocated_value"] if i < len(cost_splits) else Decimal("0.0")
                split_metadata = dict(metadata)
                split_metadata.update({
                    "is_fractionally_split": True,
                    "split_days": split["days"],
                    "original_total_days": (parsed_end - parsed_start).days + 1,
                    "original_total_quantity": str(norm_qty),
                    "original_total_cost": str(cost_val)
                })

                records.append({
                    "facility": facility,
                    "start_date": split["start_date"],
                    "end_date": split["end_date"],
                    "quantity": split["allocated_value"],
                    "unit": norm_unit,
                    "cost": cost_split,
                    "currency": raw_currency,
                    "validation_issues": warnings,
                    "activity_metadata": split_metadata
                })
            return records

        except ValueError as val_err:
            warnings.append(f"Billing period splitting error: {str(val_err)}")
            return [{
                "facility": facility,
                "start_date": parsed_start,
                "end_date": parsed_end,
                "quantity": norm_qty,
                "unit": norm_unit,
                "cost": cost_val,
                "currency": raw_currency,
                "validation_issues": warnings,
                "activity_metadata": metadata
            }]
