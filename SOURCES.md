# Data Source Formats & Specifications

This document details the real-world format shapes, data structures, and failure vectors I researched, learned, and mapped for each of the three carbon accounting data sources in the Breathe ESG data pipeline.

---

## 1. SAP Fuel & Procurement Data

### What I Researched
I researched flat-file database extracts exported via SAP transactional directory systems (`AL11`). I focused on how raw SAP database tables (specifically financial ledger tables like `BKPF` - Accounting Document Header, and `BSEG` - Document Segment) track energy-related procurements, such as fleet diesel and facility natural gas purchasing records.

### What I Learned
In Tier 1 enterprise ERP setups, financial transactions are strictly partitioned by client codes (`MANDT`) and linked to facility plant codes (`WERKS`). I learned that:
- **European Localization**: European SAP configurations localize numerical inputs. Decimals use comma separators (e.g., `8400,00`) rather than dots, and dots are sometimes used as thousands separators.
- **Compressed Date Structures**: Date fields (like posting date `BUDAT`) are stored as compressed, unformatted 8-character strings in `YYYYMMDD` format (e.g., `20260512`).
- **Identifier Zero-Padding**: Plant codes (`WERKS`), material IDs (`MATNR`), and vendor/supplier keys (`LIFNR`) are padded with leading zeros (e.g. plant `1010` is padded to `0000001010` internally, though often exported as `1010` or `0101`).

### My Sample Data Shape & Why
I structured my sample data shape using the following semicolon-delimited CSV structure:

```csv
MANDT;BELNR;BUDAT;MATNR;MAKTX;MENGE;MEINS;WRBTR;WAERS;LIFNR;NAME1;WERKS
100;5105621006;20260512;MAT-FUEL-01;DIESEL KRAFTSTOFF;8400,00;LTR;10920,00;EUR;0000103420;SHELL DEUTSCHLAND;1010
```

* **Why I structured it this way**: 
  - I used raw SAP column headers (`MANDT`, `BELNR`, `BUDAT`, etc.) to verify that my ingestion processor mapping engine accurately maps raw ERP keys to canonical fields (e.g. mapping `MENGE` to `quantity` and `MEINS` to `unit`).
  - I utilized a semicolon delimiter (`;`) because it represents the standard export separator for German SAP systems.
  - I embedded European comma decimals (`8400,00` and `10920,00`) to test and prove that my normalization cleanses European numerical notations before float casting.
  - I utilized raw unformatted dates (`20260512`) to validate my processor's parsing logic for raw SAP temporal stamps.

### What Would Break in a Real Deployment
- **Extraction Schema Drift**: If the SAP export script changes the output fields (e.g. swapping `WRBTR` document currency amount for `DMBTR` local currency amount), my parser will fail to find the cost column.
- **Varying Ledger Field Names**: If different regional subsidiaries configure different field abbreviations (e.g. using `MENGE` in Germany and `QTY` in the US), my parser's column resolution fails unless explicitly configured with translation dictionaries.
- **Unmapped Plant Codes**: If the ERP records transactions for a new plant (`WERKS = "1020"`) before my database profile registration, the record will ingest successfully but flag a critical warning indicating the facility is unmapped.

---

## 2. Utility Electricity Data

### What I Researched
I researched standard CSV exports retrieved from regional utility grids and commercial customer portals (such as E.ON, PG&E, and Duke Energy).

### What I Learned
I learned that commercial utility bills are rarely clean or formatted consistently:
- **Peak and Off-Peak Splits**: Commercial utility invoices often split active electricity consumption into peak and off-peak categories to match time-of-use tariffs.
- **Temporal Staggering**: Invoices do not align with clean calendar months. Billing periods are staggered based on monthly meter-reading schedules (e.g., Dec 15 to Jan 14).
- **Omission of Cycle Starts**: Portal CSV exports often omit the billing period start date, exporting only the period end/invoice date, which makes pro-rating difficult.

### My Sample Data Shape & Why
I structured my sample utility export shape as follows:

```csv
Facility_Name,Billing_Period_Start,Billing_Period_End,Peak_Usage_kWh,OffPeak_Usage_kWh,Unit,Cost,Currency,Provider
Munich HQ,2026-05-12,2026-06-11,400,220,kWh,124.00,EUR,E.ON
```

* **Why I structured it this way**:
  - I separated usage into `Peak_Usage_kWh` and `OffPeak_Usage_kWh` to test my parser's capability to aggregate split consumption metrics into a single total value.
  - I used a non-calendar cycle (`2026-05-12` to `2026-06-11`) to validate my fractional day-splitting algorithm, proving that my engine correctly pro-rates consumption to May (20 days) and June (11 days) rather than dumping all emissions into a single month.
  - I included standard keys like `Unit` and `Cost` to verify standard conversion mapping.

### What Would Break in a Real Deployment
- **Omission of Period End Date**: If the utility portal fails to provide the `Billing_Period_End` date, my pro-ration splitter cannot calculate the daily consumption rate, causing a fatal parsing exception.
- **Format Column Drift**: If the portal updates its schema and nests peak/off-peak metrics into a JSON object or splits them into three tiers (Peak, Mid-Peak, Off-Peak), the column mapping breaks.
- **Facility Profile Mismatches**: If a utility file registers a facility as "Munich-HQ-Admin" but my system has it stored as "Munich HQ", the facility lookup fails.

---

## 3. Corporate Travel Data

### What I Researched
I researched real-time event-driven JSON payloads from modern corporate travel booking platforms (such as Navan, Concur, or TripActions API webhooks) and matching administrative CSV backup spreadsheets.

### What I Learned
I learned that:
- **Webhook Integration**: Modern corporate travel systems emit transaction arrays as soon as travel bookings are finalized or modified.
- **Omission of Distance**: Travel portals record bookings but rarely calculate flight distance directly, exporting only origin and destination airport IATA codes (e.g. `SFO` $\rightarrow$ `CDG`).
- **Unit Divergence**: Travel data mixes distance (miles/km for flights/ground) and count (room-nights for hotel lodging) metrics in the same file.

### My Sample Data Shape & Why
I structured my sample corporate travel webhook payload as follows:

```json
{
  "Employee_ID": "EMP-4992",
  "Travel_Type": "Flight",
  "Travel_Date": "2026-05-20",
  "From_Airport": "SFO",
  "To_Airport": "CDG",
  "Cabin_Class": "Business",
  "Cost": "2850"
}
```

* **Why I structured it this way**:
  - I used a JSON format to test my poly-morphic travel parser (which automatically detects and handles JSON webhook inputs vs administrative CSV rows).
  - I used airport IATA codes (`From_Airport: SFO`, `To_Airport: CDG`) to test my pre-seeded airport coordinate directory and the accuracy of my Haversine geodesic distance calculation.
  - I included `Cabin_Class: Business` to verify that my parser can extract metadata to apply aviation emission factor multipliers.

### What Would Break in a Real Deployment
- **Unseeded IATA Airport Codes**: If an employee travels through a minor municipal airport (e.g. `BKS`) not present in my local coordinate database, the distance calculation fails (forcing my engine to use a 5,000 km fallback and alert the analyst).
- **Multi-Segment Flights**: If the third-party system sends a multi-stop flight itinerary (e.g. `SFO -> JFK -> LHR`), my current parser will fail to compute the segments recursively unless upgraded to loop through array segment points.
- **JSON Payload Key Changes**: If the travel platform shifts its API keys (e.g., renaming `Travel_Type` to `booking_category`), the parser will fail to map the activity type.
