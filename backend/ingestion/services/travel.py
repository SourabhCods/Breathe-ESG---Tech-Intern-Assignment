import csv
import json
import io
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Union
from .base import BaseIngestionProcessor
from .utils import convert_unit, parse_date, get_iata_distance


class CorporateTravelProcessor(BaseIngestionProcessor):
    """
    Corporate Travel processor.
    Handles flight emissions (Scope 3) with IATA code conversions, Haversine formulas,
    cabin class adjustments, and lodging hotel room-nights.
    Parses JSON webhook payloads and CSV exports.
    """

    def get_ghg_scope(self) -> str:
        return "Scope 3"

    def get_activity_type(self) -> str:
        return "travel"

    def parse_source(self, payload: Union[str, bytes, Dict[str, Any], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Parses JSON webhook data or CSV flat file contents.
        """
        if isinstance(payload, dict):
            # Check if it is a wrapped API payload containing a bookings list
            if "bookings" in payload:
                timestamp = payload.get("extract_timestamp") or ""
                bookings = payload["bookings"]
                for b in bookings:
                    if isinstance(b, dict):
                        b["_extract_timestamp"] = timestamp
                return bookings
            return [payload]
        elif isinstance(payload, list):
            return payload

        decoded = payload if isinstance(payload, str) else payload.decode("utf-8")
        if decoded.startswith("\ufeff"):
            decoded = decoded[1:]

        # Check if JSON structure
        trimmed = decoded.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed = json.loads(trimmed)
                if isinstance(parsed, dict) and "bookings" in parsed:
                    timestamp = parsed.get("extract_timestamp") or ""
                    bookings = parsed["bookings"]
                    for b in bookings:
                        if isinstance(b, dict):
                            b["_extract_timestamp"] = timestamp
                    return bookings
                return [parsed] if isinstance(parsed, dict) else parsed
            except json.JSONDecodeError:
                pass

        # Otherwise parse as standard CSV
        reader = csv.DictReader(io.StringIO(decoded), delimiter=",")
        if reader.fieldnames:
            reader.fieldnames = [h.strip() for h in reader.fieldnames]
        return list(reader)

    def validate(self, raw_data: Dict[str, Any]) -> List[str]:
        issues: List[str] = []

        travel_type = str(raw_data.get("category") or raw_data.get("Travel_Type") or "").strip()
        if not travel_type:
            issues.append("Missing Travel_Type (Flight, Hotel, or Ground).")
            return issues

        emp_id = raw_data.get("employee_id") or raw_data.get("Employee_ID") or raw_data.get("Employee")
        if not emp_id:
            issues.append("Missing Employee reference ID.")

        t_type = travel_type.lower()
        details = raw_data.get("details") or {}
        if t_type == "flight":
            from_a = details.get("origin_airport") or raw_data.get("From_Airport") or raw_data.get("From")
            to_a = details.get("destination_airport") or raw_data.get("To_Airport") or raw_data.get("To")
            if not from_a or not to_a:
                issues.append("Flight travel missing origin/destination IATA code.")
        elif t_type == "hotel":
            nights = details.get("room_nights") or raw_data.get("Hotel_Nights") or raw_data.get("Room_Nights") or raw_data.get("Nights")
            if not nights:
                issues.append("Hotel lodging missing nights count.")
        elif t_type in ["ground", "car", "train", "rail", "taxi", "ground_transport"]:
            dist = details.get("distance_miles") or details.get("distance_km") or raw_data.get("Distance") or raw_data.get("Distance_KM") or raw_data.get("Distance_Miles") or raw_data.get("Mileage")
            if not dist:
                issues.append("Ground transport missing distance or mileage value.")

        return issues

    def normalize(self, raw_data: Dict[str, Any], organization_id: int) -> List[Dict[str, Any]]:
        warnings: List[str] = []

        # 1. Base Attributes
        raw_emp = raw_data.get("employee_id") or raw_data.get("Employee_ID") or raw_data.get("Employee") or ""
        raw_travel_type = str(raw_data.get("category") or raw_data.get("Travel_Type") or "").strip().lower()
        
        # Map ground transport aliases
        if raw_travel_type == "ground_transport":
            raw_travel_type = "ground"
            
        raw_date = (
            raw_data.get("Travel_Date") or
            raw_data.get("Start_Date") or
            raw_data.get("Date") or
            raw_data.get("booking_date") or
            raw_data.get("booking_dt") or
            raw_data.get("_extract_timestamp") or ""
        )
        raw_cost = raw_data.get("spend") or raw_data.get("Cost") or raw_data.get("Amount") or ""
        raw_currency = raw_data.get("currency") or raw_data.get("Currency") or "EUR"

        # Parse date
        parsed_date, date_warns = parse_date(raw_date)
        warnings.extend(date_warns)

        # Parse cost
        cost_val = None
        if raw_cost:
            try:
                cost_val = Decimal(str(raw_cost).strip().replace(",", "."))
            except (ValueError, TypeError, ArithmeticError):
                warnings.append(f"Invalid travel cost: '{raw_cost}'.")

        # Initialise fields
        start_dt = parsed_date
        end_dt = parsed_date
        quantity = Decimal("0.0")
        unit = "km"
        metadata = {
            "employee_id": str(raw_emp).strip(),
            "raw_travel_type": raw_travel_type
        }
        
        details = raw_data.get("details") or {}

        # 2. Flight Ingestion
        if raw_travel_type == "flight":
            from_airport = str(details.get("origin_airport") or raw_data.get("From_Airport") or raw_data.get("From") or "").strip().upper()
            to_airport = str(details.get("destination_airport") or raw_data.get("To_Airport") or raw_data.get("To") or "").strip().upper()
            cabin_class = str(details.get("cabin_class") or raw_data.get("Cabin_Class") or raw_data.get("Class") or "Economy").strip()
            
            # Map cabin multipliers (standard Scope 3 aviation multipliers)
            cabin_multipliers = {
                "economy": 1.0,
                "premium economy": 1.5,
                "business": 2.5,
                "first": 4.0
            }
            multiplier = cabin_multipliers.get(cabin_class.lower(), 1.0)
            
            # Determine distance (Haversine lookup versus provided distance)
            raw_dist = details.get("distance_km") or details.get("distance_miles") or raw_data.get("Distance_KM") or raw_data.get("Distance")
            if raw_dist:
                try:
                    distance_val = float(str(raw_dist).strip().replace(",", "."))
                    # Unit conversion if miles
                    raw_dist_unit = "miles" if details.get("distance_miles") else str(raw_data.get("Distance_Unit") or "km").strip()
                    norm_qty, norm_unit, unit_warns = convert_unit(distance_val, raw_dist_unit, default_target="km", field_label="distance")
                    quantity = norm_qty
                    unit = norm_unit
                    warnings.extend(unit_warns)
                except (ValueError, TypeError):
                    warnings.append(f"Invalid distance provided '{raw_dist}'; invoking Great-Circle haversine lookup.")
                    calc_dist, lookup_warns = get_iata_distance(from_airport, to_airport)
                    quantity = Decimal(str(calc_dist))
                    unit = "km"
                    warnings.extend(lookup_warns)
            else:
                # Great-Circle distance lookups
                calc_dist, lookup_warns = get_iata_distance(from_airport, to_airport)
                quantity = Decimal(str(calc_dist))
                unit = "km"
                warnings.extend(lookup_warns)

            metadata.update({
                "from_airport": from_airport,
                "to_airport": to_airport,
                "cabin_class": cabin_class,
                "cabin_emission_multiplier": multiplier,
                "calculated_great_circle_km": float(quantity),
                "carrier": str(details.get("carrier") or raw_data.get("Carrier") or "").strip()
            })

        # 3. Hotel Ingestion
        elif raw_travel_type == "hotel":
            raw_nights = details.get("room_nights") or raw_data.get("Hotel_Nights") or raw_data.get("Room_Nights") or raw_data.get("Nights") or "0"
            raw_nights_unit = str(raw_data.get("Nights_Unit") or "room-nights").strip()
            
            try:
                nights_count = Decimal(str(raw_nights).strip())
            except (ValueError, TypeError, ArithmeticError):
                warnings.append(f"Invalid hotel nights '{raw_nights}', defaulted to 1.")
                nights_count = Decimal("1.0")

            norm_qty, norm_unit, unit_warns = convert_unit(nights_count, raw_nights_unit, default_target="room-nights", field_label="room-nights")
            quantity = norm_qty
            unit = norm_unit
            warnings.extend(unit_warns)

            # Set end_date based on nights count
            if start_dt:
                end_dt = start_dt + timedelta(days=int(nights_count))

            metadata.update({
                "hotel_name": str(details.get("hotel_name") or raw_data.get("Hotel_Name") or "").strip(),
                "hotel_city": str(details.get("city") or raw_data.get("City") or raw_data.get("Location") or "").strip(),
                "hotel_nights": int(nights_count),
                "hotel_country": str(details.get("country") or details.get("hotel_country") or raw_data.get("Hotel_Country") or raw_data.get("Country") or "").strip(),
                "hotel_rooms": int(details.get("number_of_rooms") or raw_data.get("Number_of_Rooms") or raw_data.get("Rooms") or 1)
            })

        # 4. Ground Transport Ingestion
        elif raw_travel_type in ["ground", "car", "train", "rail", "taxi"]:
            raw_dist = details.get("distance_miles") or details.get("distance_km") or raw_data.get("Distance") or raw_data.get("Distance_KM") or raw_data.get("Distance_Miles") or raw_data.get("Mileage") or "0"
            raw_dist_unit = "miles" if details.get("distance_miles") else str(raw_data.get("Distance_Unit") or "km").strip()
            
            try:
                dist_val = float(str(raw_dist).strip().replace(",", "."))
            except (ValueError, TypeError):
                warnings.append(f"Invalid ground transport distance '{raw_dist}', defaulted to 0.0.")
                dist_val = 0.0

            norm_qty, norm_unit, unit_warns = convert_unit(dist_val, raw_dist_unit, default_target="km", field_label="distance")
            quantity = norm_qty
            unit = norm_unit
            warnings.extend(unit_warns)

            metadata.update({
                "transport_mode": raw_travel_type,
                "vehicle_type": str(details.get("vehicle_type") or raw_data.get("Vehicle_Type") or raw_data.get("Car_Class") or "Standard").strip(),
                "fuel_type": str(details.get("fuel_type") or raw_data.get("Fuel_Type") or "Unknown").strip()
            })

        else:
            warnings.append(f"Unrecognized travel type '{raw_travel_type}'.")
            metadata.update({"unrecognized_type": raw_travel_type})

        return [{
            "facility": None,  # Scope 3 travel is not assigned to a single plant facility
            "start_date": start_dt,
            "end_date": end_dt,
            "quantity": quantity,
            "unit": unit,
            "cost": cost_val,
            "currency": raw_currency,
            "validation_issues": warnings,
            "activity_metadata": metadata
        }]
