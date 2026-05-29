import csv
import io
from decimal import Decimal
from typing import List, Dict, Any, Union
from .base import BaseIngestionProcessor
from .utils import convert_unit, parse_date
from ..models import FacilityProfile


class SAPFuelProcessor(BaseIngestionProcessor):
    """
    SAP Fuel & Procurement processor.
    Ingests semicolon-separated CSVs, translates German headers, pads supplier/material IDs,
    converts European decimal formats, and performs facility mappings.
    """

    def get_ghg_scope(self) -> str:
        return "Scope 1"

    def get_activity_type(self) -> str:
        return "fuel"

    def parse_source(self, payload: Union[str, bytes]) -> List[Dict[str, Any]]:
        """
        Parses semicolon-separated CSV content.
        """
        decoded = payload if isinstance(payload, str) else payload.decode("utf-8")
        # Handle BOM if present
        if decoded.startswith("\ufeff"):
            decoded = decoded[1:]

        # Standard semicolon delimiter for German SAP exports
        reader = csv.DictReader(io.StringIO(decoded), delimiter=";")
        
        # Trim header whitespace
        if reader.fieldnames:
            reader.fieldnames = [h.strip() for h in reader.fieldnames]

        return list(reader)

    def validate(self, raw_data: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        raw_data_upper = {str(k).strip().upper(): v for k, v in raw_data.items()}

        # Check for plant
        plant = raw_data_upper.get("WERK") or raw_data_upper.get("WERKS") or raw_data_upper.get("PLANT")
        if plant is None or str(plant).strip() == "":
            issues.append("Missing SAP plant/WERK code.")

        # Check for UoM (unit of measure)
        unit = raw_data_upper.get("MEINS") or raw_data_upper.get("UNIT")
        if unit is None or str(unit).strip() == "":
            issues.append("Missing Unit of Measure (MEINS).")

        # Check for quantity
        menge = raw_data_upper.get("MENGE") or raw_data_upper.get("QUANTITY")
        if menge is None or str(menge).strip() == "":
            issues.append("Missing quantity (Menge) field.")
        else:
            try:
                # Clean European decimal first
                val_clean = str(menge).strip()
                if "," in val_clean and "." in val_clean:
                    val_clean = val_clean.replace(".", "").replace(",", ".")
                elif "," in val_clean:
                    val_clean = val_clean.replace(",", ".")
                Decimal(val_clean)
            except (ValueError, TypeError, ArithmeticError):
                issues.append("Corrupted numerical quantity (Menge) field.")

        return issues

    def normalize(self, raw_data: Dict[str, Any], organization_id: int) -> List[Dict[str, Any]]:
        warnings: List[str] = []
        raw_data_upper = {str(k).strip().upper(): v for k, v in raw_data.items()}

        # 1. Header mapping
        raw_plant = raw_data_upper.get("WERK") or raw_data_upper.get("WERKS") or raw_data_upper.get("PLANT") or ""
        raw_unit = raw_data_upper.get("MEINS") or raw_data_upper.get("UNIT") or ""
        raw_quantity = raw_data_upper.get("MENGE") or raw_data_upper.get("QUANTITY") or ""
        raw_cost = raw_data_upper.get("WRBTR") or raw_data_upper.get("KOSTEN") or raw_data_upper.get("COST") or ""
        raw_date_str = (
            raw_data_upper.get("BUDAT") or
            raw_data_upper.get("BUCHUNGSDATUM") or
            raw_data_upper.get("DATUM") or
            raw_data_upper.get("DATE") or ""
        )
        raw_vendor = (
            raw_data_upper.get("NAME1") or
            raw_data_upper.get("VENDOR_NAME") or
            raw_data_upper.get("SUPPLIER") or
            raw_data_upper.get("VENDOR") or ""
        )
        raw_supplier_id = (
            raw_data_upper.get("LIFNR") or
            raw_data_upper.get("SUPPLIER_ID") or
            raw_data_upper.get("LIEFERANT") or ""
        )
        raw_material_id = (
            raw_data_upper.get("MATNR") or
            raw_data_upper.get("MATERIAL_ID") or
            raw_data_upper.get("MATERIALNUMMER") or ""
        )
        raw_vehicle = raw_data_upper.get("VEHICLE_ID") or raw_data_upper.get("FAHRZEUG") or ""

        # 2. Leading Zero Padding for numeric IDs
        # SAP Plant/WERK codes are typically 4 characters
        plant_code = str(raw_plant).strip()
        if plant_code.isdigit():
            plant_code = plant_code.zfill(4)

        # Supplier/Vendor IDs are typically 10 characters in SAP
        supplier_id = str(raw_supplier_id).strip()
        if supplier_id.isdigit():
            supplier_id = supplier_id.zfill(10)

        # Material IDs are typically 10 characters
        material_id = str(raw_material_id).strip()
        if material_id.isdigit():
            material_id = material_id.zfill(10)

        # 3. Facility lookup using padded Plant Code
        facility = None
        if plant_code:
            facility = FacilityProfile.objects.filter(
                organization_id=organization_id,
                plant_code=plant_code
            ).first()
            if not facility:
                warnings.append(f"Plant code '{plant_code}' is not mapped to any Facility Profile.")
        else:
            warnings.append("Plant code is empty; could not resolve Facility Profile.")

        # 4. Clean European decimal commas ('4288,38' -> '4288.38')
        def clean_european_decimal(val_str: str) -> str:
            val_clean = str(val_str).strip()
            # If it uses dot as thousands separator and comma as decimal separator, e.g., 4.288,38
            if "," in val_clean and "." in val_clean:
                # Remove dot thousands and convert comma to dot
                val_clean = val_clean.replace(".", "").replace(",", ".")
            elif "," in val_clean:
                # Just replace comma with dot
                val_clean = val_clean.replace(",", ".")
            return val_clean

        clean_qty = clean_european_decimal(raw_quantity)
        clean_cst = clean_european_decimal(raw_cost) if raw_cost else None

        # 5. Date Normalization
        parsed_dt, date_warns = parse_date(raw_date_str)
        warnings.extend(date_warns)

        # 6. Unit & Quantity Normalization (Default target L)
        # Check if it looks like a mass unit, if so standardise to kg, otherwise L
        target_default = "kg" if str(raw_unit).strip().upper() in ["KG", "TONS", "TONNE", "TONNES", "TON"] else "L"
        norm_qty, norm_unit, unit_warns = convert_unit(clean_qty, raw_unit, default_target=target_default, field_label="quantity (Menge)")
        warnings.extend(unit_warns)

        # Cost parsing
        cost_val = None
        if clean_cst:
            try:
                cost_val = Decimal(clean_cst)
            except (ValueError, TypeError, ArithmeticError):
                warnings.append(f"Invalid cost format: '{raw_cost}'.")

        # Construct metadata
        activity_metadata = {
            "sap_plant_code": plant_code,
            "sap_supplier_id": supplier_id,
            "sap_material_id": material_id,
            "vehicle_id": str(raw_vehicle).strip(),
            "vendor_name": str(raw_vendor).strip(),
            "raw_quantity": str(raw_quantity).strip(),
            "raw_unit": str(raw_unit).strip(),
            "raw_cost": str(raw_cost).strip()
        }

        return [{
            "facility": facility,
            "start_date": parsed_dt,
            "end_date": parsed_dt,  # Point-in-time fuel purchase
            "quantity": norm_qty,
            "unit": norm_unit,
            "cost": cost_val,
            "currency": "EUR",
            "validation_issues": warnings,
            "activity_metadata": activity_metadata
        }]
