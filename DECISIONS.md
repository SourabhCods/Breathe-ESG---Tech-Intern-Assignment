# Technical Decisions Log: ESG Ingestion & Normalization Architecture

This document logs the architectural design decisions, ingestion strategies, ambiguity resolutions, and regulatory compliance choices I have implemented in the Breathe ESG data pipeline. It is structured to detail my data modeling judgments, edge-case handlings, and audit trail controls for evaluation by the engineering and compliance assessment panels.

---

## Section 1: Ingestion Mechanisms & Technical Justifications

To ingest raw activity data across the enterprise landscape, I establish structured data boundary conditions that balance real-world operational constraints with high-fidelity compliance requirements.

### 1. SAP Fuel & Procurement
* **Ingestion Method**: Semicolon-separated CSV flat-file directory dump (scheduled automated transfers via SAP `AL11` file shares).
* **Technical & Operational Justification**: 
  In Tier 1 enterprise deployments, exposing synchronous transactional interfaces—such as real-time SAP Gateway `OData` REST services or executing Remote Function Calls (RFCs) via SAP BAPIs—is typically blocked. Security firewalls, strict network routing tables, and client-side database access approvals create lengthy bureaucratic delays (often taking 6–9 months) during onboarding. Furthermore, synchronous calls create runtime dependencies on ERP transactional availability and introduce substantial SAP licensing fees based on direct API call volumes.
  
  Utilizing flat-file directory extracts via the `AL11` transaction code represents the production-grade industry standard. SAP systems natively dump reports to localized application directory servers on scheduled cron jobs. By integrating an append-only flat-file ingestion worker, I establish a secure, asynchronous boundary condition that client IT departments can approve within days, bypassing ERP runtime dependencies and synchronous API license overhead.

### 2. Utility Electricity Data
* **Ingestion Method**: Structured portal-extracted CSV dumps.
* **Technical & Operational Justification**: 
  PDF utility invoices are inherently unstructured and subject to frequent layout adjustments by regional utility vendors, making optical character recognition (OCR) and regex-based PDF scraping fragile, error-prone, and high-maintenance. 
  
  Direct CSV extracts from customer portals (such as PG&E, E.ON, or Duke Energy) provide structured interval data. Critically, portal CSVs expose granular metrics differentiating active power consumption (**kWh**) from peak/off-peak usage distributions. Access to these metrics allows my platform to support advanced market-based Scope 2 carbon accounting (incorporating power factors and utility-specific contractual tariffs) rather than relying on crude, flat-rate monthly estimations.

### 3. Corporate Travel
* **Ingestion Method**: Asynchronous JSON Webhook payloads (Primary) with structured CSV uploads (Administrative Fallback).
* **Technical & Operational Justification**: 
  Modern corporate travel management systems (such as Concur, Navan, or TripActions) operate on event-driven travel booking triggers. I expose an asynchronous JSON Webhook endpoint that receives real-time transaction event arrays whenever travel bookings are finalized or modified. This reduces latency and guarantees continuous audit logs. 
  
  For administrative adjustments, historical reconciliations, or offline travel agencies, I support a flat-file CSV upload schema using the same parser strategy, ensuring manual uploads undergo identical normalization, Haversine geodesics, and validation pipelines as the automated API streams.

---

## Section 2: Technical Ambiguities & Edge-Case Resolutions

My data pipelines defensively process incomplete or corrupted inputs while protecting the immutability of the source audit trail. I resolve ambiguities systematically:

### A. Non-Calendar Utility Billing Periods & Year Boundaries
* **The Challenge**: Utility billing cycles rarely align with calendar months (e.g., Dec 15 to Jan 14). Assigning the entire bill's consumption to the month of the invoice date introduces major reporting errors, especially across calendar years where grid carbon intensities shift.
* **The Resolution**: 
  I implement a fractional day-splitting algorithm. The total usage is divided by the duration of the cycle to determine a daily average consumption rate:
  
  $$\text{Daily Consumption} = \frac{\text{Total Consumption}}{\text{Total Days}}$$
  
  When a billing period crosses monthly or annual boundaries, my engine dynamically generates distinct, pro-rated normalized database records mapping to each calendar month. 
  
  *Regulatory Impact*: When a billing period crosses a year boundary (e.g., Dec 15, 2025, to Jan 14, 2026), my splitter isolates the December days from the January days. This guarantees that the specific grid emission factors (which change annually based on grid greening metrics) are applied to each segment with zero temporal leakage, maintaining strict compliance with the GHG Protocol Corporate Standard.

### B. Missing Utility Start Dates
* **The Challenge**: Utility portal exports occasionally omit the billing cycle start date, providing only the invoice end date.
* **The Resolution**: 
  Instead of failing the entire file import, my strategy processor infers the billing start date by executing a defensive 30-day lookback calculation from the parsed end date:
  
  $$\text{Inferred Start Date} = \text{End Date} - 30 \text{ days}$$
  
  Crucially, I do not perform this inference silently. The record's database status is flagged as `'FLAGGED'` (warning), and a descriptive warning message—`"Missing Billing_Period_Start. Inferred as 30 days prior..."`—is appended to `validation_issues`. This raises awareness on the analyst dashboard while preventing data omission.

### C. Missing Travel Distances & Geodesic Fallbacks
* **The Challenge**: Corporate travel logs frequently omit flight distances, exporting only origin and destination airport IATA codes (e.g., `DEL` $\rightarrow$ `LHR`).
* **The Resolution**: 
  My Corporate Travel strategy intercepts IATA codes, normalizes them to uppercase, and queries a local coordinate lookup service containing pre-seeded coordinate structures. If both airports are resolved, the engine computes the geodesic flight distance using the **Haversine formula**:
  
  $$d = 2R \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta\phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta\lambda}{2}\right)}\right)$$
  
  If the coordinate lookup fails (e.g., an unknown municipal airport code), my engine applies a conservative fallback of **5,000 km** to prevent under-reporting emissions. Simultaneously, it appends a critical validation warning (`"Unknown IATA code, using default distance fallback."`), sets the record's status to `'FLAGGED'`, and alerts the analyst on the dashboard to input the true mileage.

### D. SAP Header Normalization & European Numeric Cleanse
* **The Challenge**: SAP configuration scripts generate varied, localized headers (e.g., `"Menge"`, `"MENGE"`, `"Quantity"`) and export values using European comma notation (e.g., `"12500,80"` or `"4.288,38"`).
* **The Resolution**: 
  Before validation, my strategy processor sanitizes the input dictionary by mapping all keys to stripped, uppercase representations. Decimal values are pre-cleaned: dots (used as thousands separators in some configurations) are stripped, and commas are replaced with dots (e.g., `"4.288,38"` $\rightarrow$ `"4288.38"`) recursively. This ensures standard float casting succeeds before the validation validator executes.

### E. SAP Unit Multiplicity & Standard Unit Normalization
* **The Challenge**: SAP procurement tracks fuel in multiple physical measurements, including volume (Liters, Gallons, Cubic Meters) and mass (Metric Tons - `MT`, kilograms).
* **The Resolution**: 
  I implemented standard conversion scales in `utils.py`. Volume units (Liters, Gallons, Cubic Meters) map to canonical volume in Liters (`L`), and mass units (Kilograms, Tons, Metric Tons) map to canonical mass in Kilograms (`kg`). The engine standardizes raw units to these target units using conversion factors (e.g. `MT` -> `kg` with a factor of `1000.0`, `M3` -> `L` with a factor of `1000.0`, `GAL` -> `L` with a factor of `3.78541`). Standardizing to canonical mass/volume metrics keeps physical quantities consistent for subsequent Scope 1 emissions calculations, which are applied directly to either mass or volume metrics.

### F. Optional Vehicle References for Alert Fatigue Mitigation (UX Optimization)
* **The Challenge**: Typical fleet logs associate fuel purchases with asset tags (`VEHICLE_ID` / `FAHRZEUG`). If missing, raising a blocking validation warning flags nearly every transaction, creating noise that obscures critical errors like unmapped plants.
* **The Resolution**: 
  I shifted missing vehicle references from a blocking validation failure to an optional metadata attribute. My parser still extracts and stores the vehicle reference in the metadata if present, but perfectly normalized rows without vehicle references remain clean. This reduces dashboard noise and keeps the analyst focused on structural date and plant mismatches.

---

## Section 3: Product Manager Alignment & Regulatory Questions

To advance the platform toward regulatory audit readiness, I have compiled the following strategic engineering questions to align with product management:

### 1. Flight Cabin Class Multipliers
> *“Which regulatory emission coefficient framework (e.g., DEFRA, GHG Protocol, or ICAO) must I map to the cabin class multipliers currently stored in metadata (Economy: 1.0, Premium: 1.5, Business: 2.5, First Class: 4.0)? Should the multipliers themselves be dynamically configurable per tenant?”*

### 2. Multi-Currency Reconciliation Strategy
> *“For SAP transactions arriving in localized currencies (e.g. INR, USD, GBP), should I draw exchange rates from a live, time-indexed Forex API using the specific posting date (`BUDAT`), or should I align with corporate finance standards by utilizing a static annual corporate financial exchange table uploaded once per reporting period?”*

### 3. Plant Code Lifecycle Automation
> *“What is the automated operational lifecycle when an unmapped SAP plant code (`WERKS`) is detected? Should I build a self-service Facility Profile mapping UI that prompts analysts to map unmapped plant codes directly from the dashboard, or should they be managed via a centralized admin profile?”*

### 4. Data Lock Exemption & Compensating Transactions
> *“Once a record has been marked `APPROVED` and locked (`is_locked = True`), how should retroactive corrections be handled? Does corporate compliance require a strict append-only audit trail where corrections can only be made via a reverse-compensating adjustment row (similar to bookkeeping standard practices), or should I build an authenticated administrative escalation path to unlock and modify records directly?”*
