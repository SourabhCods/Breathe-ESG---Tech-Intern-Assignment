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
        Parses CSV content, dynamically detecting comma vs. semicolon delimiter.
        """
        decoded = payload if isinstance(payload, str) else payload.decode("utf-8")
        if decoded.startswith("\ufeff"):
            decoded = decoded[1:]

        first_line = decoded.split("\n")[0]
        delimiter = ";" if ";" in first_line else ","

        reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
        if reader.fieldnames:
            reader.fieldnames = [h.strip() for h in reader.fieldnames]

        return list(reader)

    def validate(self, raw_data: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        raw_data_upper = {str(k).strip().upper(): v for k, v in raw_data.items()}

        facility_name = (
            raw_data_upper.get("FACILITY_NAME") or
            raw_data_upper.get("FACILITY") or
            raw_data_upper.get("FACILITY_ID") or
            raw_data_upper.get("METER_REF")
        )
        if not facility_name or str(facility_name).strip() == "":
            issues.append("Missing facility identification (Facility_Name).")

        end_date_str = (
            raw_data_upper.get("BILLING_PERIOD_END") or
            raw_data_upper.get("END_DATE") or
            raw_data_upper.get("BILL_END")
        )
        if not end_date_str or str(end_date_str).strip() == "":
            issues.append("Missing billing period end date.")

        # Check consumption metrics
        peak = raw_data_upper.get("PEAK_USAGE_KWH") or raw_data_upper.get("ACTIVE_PEAK_KWH")
        off_peak = raw_data_upper.get("OFFPEAK_USAGE_KWH") or raw_data_upper.get("ACTIVE_OFFPEAK_KWH")
        total_qty = (
            raw_data_upper.get("KWH_CONSUMED") or
            raw_data_upper.get("USAGE") or
            raw_data_upper.get("CONSUMPTION")
        )

        if not total_qty and not (peak or off_peak):
            issues.append("No consumption metrics found (kWh_Consumed or Peak/Off-Peak split).")

        return issues

    def normalize(self, raw_data: Dict[str, Any], organization_id: int) -> List[Dict[str, Any]]:
        warnings: List[str] = []
        raw_data_upper = {str(k).strip().upper(): v for k, v in raw_data.items()}

        # 1. Facility resolution
        raw_facility = (
            raw_data_upper.get("FACILITY_NAME") or
            raw_data_upper.get("FACILITY") or
            raw_data_upper.get("FACILITY_ID") or
            raw_data_upper.get("METER_REF") or ""
        )
        raw_facility_str = str(raw_facility).strip()
        facility = FacilityProfile.objects.filter(
            organization_id=organization_id,
            facility_name__iexact=raw_facility_str
        ).first()

        if not facility and raw_facility_str:
            # Fallback check on plant_code
            facility = FacilityProfile.objects.filter(
                organization_id=organization_id,
                plant_code__iexact=raw_facility_str
            ).first()

        if not facility:
            warnings.append(f"Facility Profile '{raw_facility_str}' not found in organization.")

        # 2. Date parsing and inference
        raw_start_dt = (
            raw_data_upper.get("BILLING_PERIOD_START") or
            raw_data_upper.get("START_DATE") or
            raw_data_upper.get("BILL_START") or ""
        )
        raw_end_dt = (
            raw_data_upper.get("BILLING_PERIOD_END") or
            raw_data_upper.get("END_DATE") or
            raw_data_upper.get("BILL_END") or ""
        )

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
        raw_unit = raw_data_upper.get("UNIT") or raw_data_upper.get("UOM") or "kWh"
        raw_cost_str = (
            raw_data_upper.get("COST") or
            raw_data_upper.get("AMOUNT") or
            raw_data_upper.get("TOTAL_CHARGES") or
            raw_data_upper.get("CHARGES") or ""
        )
        raw_currency = raw_data_upper.get("CURRENCY") or "EUR"

        # Check for peak/off-peak split
        raw_peak = raw_data_upper.get("PEAK_USAGE_KWH") or raw_data_upper.get("ACTIVE_PEAK_KWH")
        raw_off_peak = raw_data_upper.get("OFFPEAK_USAGE_KWH") or raw_data_upper.get("ACTIVE_OFFPEAK_KWH")
        
        consumption_decimal = Decimal("0.0")
        has_split_usage = False

        if raw_peak or raw_off_peak:
            # Parse peak
            peak_val = Decimal("0.0")
            if raw_peak and str(raw_peak).strip().upper() not in ["INVALID", "NA", "N/A", ""]:
                try:
                    p_clean = str(raw_peak).strip().replace(",", ".")
                    peak_val = Decimal(p_clean)
                except (ValueError, TypeError, ArithmeticError):
                    warnings.append(f"Corrupted Peak Usage value '{raw_peak}', defaulted to 0.0.")
            
            # Parse off-peak
            off_peak_val = Decimal("0.0")
            if raw_off_peak and str(raw_off_peak).strip().upper() not in ["INVALID", "NA", "N/A", ""]:
                try:
                    op_clean = str(raw_off_peak).strip().replace(",", ".")
                    off_peak_val = Decimal(op_clean)
                except (ValueError, TypeError, ArithmeticError):
                    warnings.append(f"Corrupted Off-Peak Usage value '{raw_off_peak}', defaulted to 0.0.")
            
            consumption_decimal = peak_val + off_peak_val
            has_split_usage = True
        else:
            # Parse total general consumption
            raw_total = (
                raw_data_upper.get("KWH_CONSUMED") or
                raw_data_upper.get("USAGE") or
                raw_data_upper.get("CONSUMPTION") or "0.0"
            )
            if raw_total and str(raw_total).strip().upper() not in ["NA", "N/A", ""]:
                try:
                    t_clean = str(raw_total).strip().replace(",", ".")
                    consumption_decimal = Decimal(t_clean)
                except (ValueError, TypeError, ArithmeticError):
                    warnings.append(f"Corrupted consumption value '{raw_total}', defaulted to 0.0.")

        # Standardize consumption to kWh target
        norm_qty, norm_unit, unit_warns = convert_unit(consumption_decimal, raw_unit, default_target="kWh", field_label="consumption quantity")
        warnings.extend(unit_warns)

        # Parse cost
        cost_val = Decimal("0.0")
        if raw_cost_str:
            try:
                c_clean = str(raw_cost_str).strip().replace(",", ".")
                cost_val = Decimal(c_clean)
            except (ValueError, TypeError, ArithmeticError):
                warnings.append(f"Invalid cost format: '{raw_cost_str}'.")

        # Define metadata context
        metadata = {
            "peak_usage_kwh": str(raw_peak).strip() if raw_peak else None,
            "off_peak_usage_kwh": str(raw_off_peak).strip() if raw_off_peak else None,
            "has_split_usage": has_split_usage,
            "raw_billing_start": str(raw_start_dt).strip(),
            "raw_billing_end": str(raw_end_dt).strip(),
            "provider": str(raw_data_upper.get("PROVIDER") or "").strip()
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
