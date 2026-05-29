# Breathe ESG Ingestion & Normalization System

This is the production-grade corporate sustainability data pipeline and analytics dashboard I built for the Breathe ESG technical assessment. It features multi-tenant data boundaries, an immutable ingestion audit ledger, dynamic utility billing period splitting, Great-Circle flight distance geodesics, and a premium dark-mode analyst review interface.

---

## 1. Scope of My Implementation

I designed and engineered the following capabilities across the full stack:

- **Robust Multi-Tenancy**: I built an isolation filter (`X-Tenant-ID` header/request checking) mapping all data to separate tenant `Organization` records to prevent tenant data leakage.
- **SAP Ingestion Processor**: I implemented a parser for semicolon-delimited CSV flat-files with German header translation, zero-padded plant/vendor formatting, and European numeric conversions (e.g. converting `12.500,80` -> `12500.80`).
- **Utility Ingestion & Day-Splitting**: I created a temporal processor that pro-rates utility consumption and cost fractionally across month and year boundaries, ensuring grid emissions are calculated using accurate annual grid factors.
- **Missing Date Inference**: If utility files lack start dates, I programmatically calculate a 30-day lookback window, flagging the record for manual validation.
- **Travel Ingestion & Geodesic Calculation**: I implemented event-driven JSON Webhook ingestion with CSV uploads for corporate travel. I integrated the **Haversine formula** to calculate Great-Circle distances based on IATA airport code coordinates, applying a 5,000 km fallback if the airport code is unrecognized.
- **Append-Only Staging Row Logging**: I overrode standard ORM write operations in Python/Django to preserve all raw source imports in an immutable state for auditors.
- **Analyst Modification & Override Logs**: I designed an append-only `AuditLog` mapping old vs. new values for manual overrides, blocking edits to finalized, approved data records.
- **UX-Optimized Analyst Dashboard**: I overhauled the React UI with a dark-mode theme, interactive metric summaries, color-coded warnings, filter queries, and manual override dialog forms.
- **Testing Integrity**: I wrote **14 automated unit tests** verifying parsers, date normalizations, unit conversions (e.g., `MT` -> `kg` and `M3` -> `L`), travel structures, and splitting edge cases.

---

## 2. Tech Stack

- **Backend**: Python 3.10+, Django, Django REST Framework, SQLite (with migrations config).
- **Frontend**: React 18+, Vite, ESBuild, Vanilla CSS (Premium dark mode UI with interactive badge state transitions).

---

## 3. Local Setup Instructions

### Backend Setup
1. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```
2. **Create and activate a Python virtual environment**:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Execute database migrations**:
   ```bash
   python manage.py migrate
   ```
5. **Seed the database** (optional default values):
   ```bash
   python manage.py loaddata seed.json
   ```
6. **Start the local development server**:
   ```bash
   python manage.py runserver
   ```

### Frontend Setup
1. **Navigate to the frontend directory**:
   ```bash
   cd frontend
   ```
2. **Install node dependencies**:
   ```bash
   npm install
   ```
3. **Run Vite development server**:
   ```bash
   npm run dev
   ```

### Running Automated Tests
I wrote a unit test suite to verify the core algorithms. To execute these tests, run:
```bash
venv\Scripts\python manage.py test
```

---

## 4. Next Scalability Steps I Plan to Build

- **Production Database**: Migrate from the local SQLite store to a containerized, transaction-heavy PostgreSQL cluster.
- **Authentication Gateway**: Gate API endpoints behind standard JWT token verification with granular role access (e.g. Analyst vs. Auditor).
- **Dynamic Emission Factor Engine**: Integrate a database of dynamic, localization-aware emission factors (such as EPA eGRID, DEFRA, and ICAO) to calculate carbon footprints automatically.
- **PDF Utility Scraping**: Incorporate an OCR OCR-scraping service (like AWS Textract or Tesseract) to convert scanned utility invoices into structured formats.
