import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple, Union, Optional

# Standard IATA airport coordinates for Great-Circle distance mapping
AIRPORT_COORDINATES: Dict[str, Tuple[float, float]] = {
    "DEL": (28.5562, 77.1000),    # Delhi
    "LHR": (51.4700, -0.4543),    # London Heathrow
    "SFO": (37.6213, -122.3790),  # San Francisco
    "JFK": (40.6413, -73.7781),   # New York JFK
    "CDG": (49.0097, 2.5479),     # Paris CDG
    "DXB": (25.2532, 55.3657),    # Dubai
    "SIN": (1.3644, 103.9915),    # Singapore
    "HND": (35.5494, 139.7798),   # Tokyo Haneda
    "SYD": (-33.9461, 151.1772),  # Sydney
    "FRA": (50.0379, 8.5622),     # Frankfurt
    "MUC": (48.3538, 11.7861),     # Munich
    "AMS": (52.3105, 4.7683),     # Amsterdam
    "HKG": (22.3080, 113.9185),   # Hong Kong
}

# Unit mappings with target standard unit and conversion factors
# All volume -> Liters (L)
# All mass -> Kilograms (kg)
# All electricity -> kWh
# All distance -> Kilometers (km)
# All hotel -> Room-nights
UNIT_CONVERSIONS: Dict[str, Tuple[str, float]] = {
    # Volume to Liters (L)
    "L": ("L", 1.0),
    "LTR": ("L", 1.0),
    "LTRS": ("L", 1.0),
    "LITRE": ("L", 1.0),
    "LITRES": ("L", 1.0),
    "GAL": ("L", 3.78541),
    "GALLON": ("L", 3.78541),
    "GALLONS": ("L", 3.78541),
    "M3": ("L", 1000.0),
    "CUBIC METER": ("L", 1000.0),
    "CUBIC METERS": ("L", 1000.0),
    "CUBIC-METER": ("L", 1000.0),
    "CUBIC-METERS": ("L", 1000.0),
    
    # Mass to Kilograms (kg)
    "KG": ("kg", 1.0),
    "KILOGRAM": ("kg", 1.0),
    "KILOGRAMS": ("kg", 1.0),
    "KILOS": ("kg", 1.0),
    "TON": ("kg", 1000.0),
    "TONS": ("kg", 1000.0),
    "TONNE": ("kg", 1000.0),
    "TONNES": ("kg", 1000.0),
    "MT": ("kg", 1000.0),
    "METRIC TON": ("kg", 1000.0),
    "METRIC TONS": ("kg", 1000.0),
    "METRIC TONNE": ("kg", 1000.0),
    "METRIC TONNES": ("kg", 1000.0),
    
    # Electricity to kWh
    "KWH": ("kWh", 1.0),
    "KILOWATT-HOUR": ("kWh", 1.0),
    "KILOWATT HOUR": ("kWh", 1.0),
    "UNITS": ("kWh", 1.0),
    "UNIT": ("kWh", 1.0),
    "MWH": ("kWh", 1000.0),
    "MEGAWATT-HOUR": ("kWh", 1000.0),
    "MEGAWATT HOUR": ("kWh", 1000.0),

    # Distance to Kilometers (km)
    "KM": ("km", 1.0),
    "KILOMETER": ("km", 1.0),
    "KILOMETERS": ("km", 1.0),
    "MILE": ("km", 1.60934),
    "MILES": ("km", 1.60934),
    "MI": ("km", 1.60934),

    # Hotel nights to Room-Nights
    "ROOM-NIGHTS": ("room-nights", 1.0),
    "ROOM NIGHTS": ("room-nights", 1.0),
    "ROOM_NIGHTS": ("room-nights", 1.0),
    "NIGHTS": ("room-nights", 1.0),
    "NIGHT": ("room-nights", 1.0),
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes Great-Circle distance in kilometers between two points using the Haversine formula.
    """
    R = 6371.0  # Earth's radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def get_iata_distance(from_code: str, to_code: str) -> Tuple[float, List[str]]:
    """
    Looks up IATA codes, calculates Great-Circle distance using Haversine, and returns warnings.
    Returns:
        (distance_km, warnings_list)
    """
    warnings: List[str] = []
    c_from = from_code.strip().upper()
    c_to = to_code.strip().upper()

    if not c_from or not c_to:
        return 5000.0, ["Missing airport IATA code, using default 5000 km distance."]

    coord_from = AIRPORT_COORDINATES.get(c_from)
    coord_to = AIRPORT_COORDINATES.get(c_to)

    if not coord_from:
        warnings.append(f"Unknown IATA code '{c_from}', using default distance fallback.")
    if not coord_to:
        warnings.append(f"Unknown IATA code '{c_to}', using default distance fallback.")

    if coord_from and coord_to:
        dist = haversine_distance(coord_from[0], coord_from[1], coord_to[0], coord_to[1])
        return round(dist, 2), warnings
    else:
        return 5000.0, warnings


def convert_unit(value: Union[float, Decimal, str], raw_unit: str, default_target: str = "L", field_label: str = "value") -> Tuple[Decimal, str, List[str]]:
    """
    Converts a value from a raw unit to the target canonical unit.
    Returns:
        (normalized_value, target_unit, warnings_list)
    """
    warnings: List[str] = []
    
    # Check for empty or NaN values
    if value is None or str(value).strip().upper() in ["NAN", "NA", "N/A", ""]:
        return Decimal("0.0"), "UNKNOWN", [f"Missing or corrupted {field_label}, set to 0.0."]

    try:
        dec_val = Decimal(str(value).strip().replace(",", "."))
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("0.0"), "UNKNOWN", [f"Corrupted numerical {field_label} '{value}', defaulted to 0.0."]

    norm_unit = str(raw_unit).strip().upper() if raw_unit else ""
    
    if not norm_unit or norm_unit in ["UNKNOWN", "NA", "N/A", ""]:
        return dec_val, default_target, [f"Missing unit UoM. Standardized to default '{default_target}'."]

    conversion = UNIT_CONVERSIONS.get(norm_unit)
    if conversion:
        target_unit, factor = conversion
        converted_val = dec_val * Decimal(str(factor))
        return converted_val, target_unit, warnings
    else:
        # Keep the raw unit if it is not mapped, and log a warning
        return dec_val, raw_unit, [f"Unrecognized unit '{raw_unit}' passed through without conversion."]


def parse_date(date_str: str) -> Tuple[Optional[date], List[str]]:
    """
    Defensively parses various date formats into a datetime.date object.
    Supports DD.MM.YYYY, YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, and variations.
    """
    if not date_str or str(date_str).strip().upper() in ["NAN", "NA", "N/A", ""]:
        return None, ["Missing date value."]

    clean_str = str(date_str).strip()
    if "T" in clean_str:
        clean_str = clean_str.split("T")[0]
    elif " " in clean_str:
        parts = clean_str.split(" ")
        if any(char in parts[0] for char in ["-", "/", "."]):
            clean_str = parts[0]

    formats = [
        "%d.%m.%Y",  # German format e.g., 31.05.2026
        "%Y-%m-%d",  # ISO format e.g., 2026-05-31
        "%d/%m/%Y",  # UK/IN format e.g., 31/05/2026
        "%m/%d/%Y",  # US format e.g., 05/31/2026
        "%Y/%m/%d",
        "%Y.%m.%d",  # Dot ISO format e.g., 2026.05.31
        "%Y%m%d",    # Raw SAP compressed format e.g., 20260512
        "%d-%b-%Y",  # Month abbreviation e.g., 01-MAY-2026
        "%d-%B-%Y",  # Full month name e.g., 01-May-2026
        "%d-%m-%Y",  # Dash format e.g., 10-05-2026
    ]

    for fmt in formats:
        try:
            parsed = datetime_parse(clean_str, fmt)
            return parsed, []
        except ValueError:
            continue

    return None, [f"Unable to parse date string '{date_str}' with standard formats."]


def datetime_parse(date_str: str, fmt: str) -> date:
    # Small helper for typed datetime parsing
    import datetime
    return datetime.datetime.strptime(date_str, fmt).date()


def split_billing_period(start_date: date, end_date: date, total_value: Decimal) -> List[Dict[str, Union[date, Decimal, int]]]:
    """
    Splits billing periods that cross calendar month boundaries fractionally.
    Returns:
        List of dicts: [
            {"start_date": date, "end_date": date, "allocated_value": Decimal, "days": int},
            ...
        ]
    """
    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    total_days = (end_date - start_date).days + 1
    if total_days <= 0:
        return []

    splits: List[Dict[str, Union[date, Decimal, int]]] = []
    current_date = start_date

    while current_date <= end_date:
        # Determine the last day of the current month
        # Move to day 28, add 4 days to ensure crossing boundary, replacement to day 1, subtract 1 day
        next_month_first = (current_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month_first - timedelta(days=1)
        
        # Overlap duration in current month
        overlap_start = current_date
        overlap_end = min(end_date, month_end)
        overlap_days = (overlap_end - overlap_start).days + 1
        
        # Calculate proportional value allocation
        proportion = Decimal(overlap_days) / Decimal(total_days)
        allocated = total_value * proportion
        
        splits.append({
            "start_date": overlap_start,
            "end_date": overlap_end,
            "allocated_value": allocated,
            "days": overlap_days
        })
        
        current_date = next_month_first

    return splits
