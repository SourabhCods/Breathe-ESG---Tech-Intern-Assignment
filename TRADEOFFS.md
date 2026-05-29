# Engineering Tradeoffs

This document outlines the three key engineering decisions I deliberately made to defer or simplify features in favor of data processing stability and audit security.

---

## 1. Deferring the Carbon Emissions Factor Database
* **What I did not build**: A live lookup engine connecting activity data to Scope 1/2/3 carbon emission factor tables (such as DEFRA, EPA, or eGRID databases).
* **My Reason**: Emission factors are highly dynamic, regional, and change annually. Implementing a database of factors would require building complex location-based utility grid lookups (e.g., eGRID subregion codes for Scope 2) and fuel density tables. To keep my project focused on the core engineering challenge—**decoupled ingestion, robust data normalization, and audit-readiness**—I normalize and validate the physical activities (`kWh`, `Liters`, `km`, `room-nights`) and defer the multiplication step.

## 2. Mocking Authentication and Seeding Tenant Roles
* **What I did not build**: A full multi-tenant user authentication system (such as OAuth2, JWT, or Django sessions with roles like Administrator/Analyst/Auditor).
* **My Reason**: Implementing full authentication would clutter the backend views and require complex configuration changes to the React frontend (login screens, tokens routing). I mapped the models (`UploadedFile` and `AuditLog`) to Django's built-in `auth.User` model to establish database traceability, but I bypass active session verification by defaulting user links to a seeded administrative analyst. This proves my data model is fully traceable without wasting development budget on standard identity plumbing.

## 3. Rejecting Silent "Auto-Correction" of Faulty Data
* **What I did not build**: Ingestion algorithms that silently drop, discard, or auto-complete corrupt data rows (such as inserting `$0.00` for missing costs, or skipping rows with NaN values without warning).
* **My Reason**: In sustainability auditing, silent data correction is a compliance violation. If a row has a missing quantity or corrupted unit, the system must retain it. I chose to save all raw records in the staging table, but I mark the normalized record as `FLAGGED` and list the exact issues in the `validation_issues` array. This keeps the data fully visible on the dashboard, forcing analysts to manually review and override the values.
