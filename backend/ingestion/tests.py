from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import date

from .models import (
    Organization,
    FacilityProfile,
    StagingRow,
    NormalizedEmissionActivity,
    AuditLog
)
from .services.utils import (
    haversine_distance,
    get_iata_distance,
    convert_unit,
    parse_date,
    split_billing_period
)
from .services import IngestionProcessorFactory


class ESGNormalizationPipelineTestCase(TestCase):
    """
    Test suite verifying correctness of calculation models, conversions, and
    strategy pipelines for Scope 1, 2, and 3 emissions processing.
    """

    def setUp(self) -> None:
        # Create Organizations (Tenants)
        self.org_alpha = Organization.objects.create(
            name="Tenant Alpha Corp",
            slug="tenant-alpha"
        )
        self.org_beta = Organization.objects.create(
            name="Tenant Beta Ltd",
            slug="tenant-beta"
        )

        # Create Facility profile mapping for SAP Plant lookup
        self.facility_hq = FacilityProfile.objects.create(
            organization=self.org_alpha,
            facility_name="Main HQ Facility",
            plant_code="DE01",
            location="Berlin, Germany"
        )

        # Create a standard user for manual edits
        self.analyst = User.objects.create_user(
            username="analyst_user",
            password="test_password"
        )

    def test_multi_tenancy_isolation(self) -> None:
        """
        Ensures data records cannot bypass Tenant Organization references.
        """
        with self.assertRaises(Exception):
            StagingRow.objects.create(
                source_type="sap",
                raw_data={"Menge": "100"}
            )

    def test_staging_row_immutability(self) -> None:
        """
        Ensures StagingRow records are strictly read-only after creation.
        """
        row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="sap",
            raw_data={"WERK": "DE01", "Menge": "100"}
        )

        # Attempt to modify raw data should raise a validation error
        with self.assertRaises(ValidationError):
            row.raw_data = {"WERK": "DE01", "Menge": "200"}
            row.save()

        # Attempt to delete staging row should raise a validation error
        with self.assertRaises(ValidationError):
            row.delete()

    def test_haversine_formula(self) -> None:
        """
        Verifies correct Great-Circle Haversine distance computations for airport routes.
        """
        # Delhi (DEL) to London Heathrow (LHR) should be ~6,710 km
        distance, warnings = get_iata_distance("DEL", "LHR")
        self.assertAlmostEqual(distance, 6710.0, delta=100.0)
        self.assertEqual(len(warnings), 0)

        # San Francisco (SFO) to New York (JFK) should be ~4,150 km
        distance_usa, warnings_usa = get_iata_distance("SFO", "JFK")
        self.assertAlmostEqual(distance_usa, 4150.0, delta=100.0)
        self.assertEqual(len(warnings_usa), 0)

        # Unknown airport code should use default fallback and append warning
        dist_fallback, warnings_fallback = get_iata_distance("XYZ", "LHR")
        self.assertEqual(dist_fallback, 5000.0)
        self.assertTrue(any("XYZ" in w for w in warnings_fallback))

    def test_unit_conversions(self) -> None:
        """
        Ensures standard unit normalization functions run cleanly and register warnings.
        """
        # Volume (Gallons to Liters)
        value, target_unit, warnings = convert_unit("100.0", "GAL")
        self.assertAlmostEqual(float(value), 378.541, places=3)
        self.assertEqual(target_unit, "L")

        # Volume (M3 to Liters)
        val_m3, target_m3, warn_m3 = convert_unit("5.5", "M3")
        self.assertEqual(float(val_m3), 5500.0)
        self.assertEqual(target_m3, "L")
        self.assertEqual(len(warn_m3), 0)

        # Mass (Metric Tons to Kilograms)
        value_mass, target_unit_mass, warnings_mass = convert_unit("2.5", "TONS")
        self.assertEqual(float(value_mass), 2500.0)
        self.assertEqual(target_unit_mass, "kg")

        # Mass (MT to Kilograms)
        val_mt, target_mt, warn_mt = convert_unit("11.20", "MT")
        self.assertEqual(float(val_mt), 11200.0)
        self.assertEqual(target_mt, "kg")
        self.assertEqual(len(warn_mt), 0)

        # Electricity (MWh to kWh)
        val_elec, target_elec, warn_elec = convert_unit("3,15", "MWH")
        self.assertEqual(float(val_elec), 3150.0)
        self.assertEqual(target_elec, "kWh")

        # Empty/NaN values
        val_nan, target_nan, warn_nan = convert_unit("NaN", "L")
        self.assertEqual(float(val_nan), 0.0)
        self.assertEqual(target_nan, "UNKNOWN")
        self.assertTrue(len(warn_nan) > 0)

    def test_date_parsing(self) -> None:
        """
        Verifies correct parsing of various date string layouts, including dotted format.
        """
        # Test German format
        parsed, warnings = parse_date("15.05.2026")
        self.assertEqual(parsed, date(2026, 5, 15))
        self.assertEqual(len(warnings), 0)

        # Test ISO format
        parsed_iso, warnings_iso = parse_date("2026-05-15")
        self.assertEqual(parsed_iso, date(2026, 5, 15))
        self.assertEqual(len(warnings_iso), 0)

        # Test YYYY.MM.DD format (SAP dot layout)
        parsed_sap, warnings_sap = parse_date("2026.05.25")
        self.assertEqual(parsed_sap, date(2026, 5, 25))
        self.assertEqual(len(warnings_sap), 0)

        # Test ISO 8601 datetime with T and Z offset
        parsed_iso_tz, warnings_iso_tz = parse_date("2026-05-28T12:00:00Z")
        self.assertEqual(parsed_iso_tz, date(2026, 5, 28))
        self.assertEqual(len(warnings_iso_tz), 0)

        # Test ISO 8601 datetime with space separator
        parsed_iso_sp, warnings_iso_sp = parse_date("2026-05-28 12:00:00")
        self.assertEqual(parsed_iso_sp, date(2026, 5, 28))
        self.assertEqual(len(warnings_iso_sp), 0)

        # Test corrupted layout
        parsed_bad, warnings_bad = parse_date("invalid-date")
        self.assertIsNone(parsed_bad)
        self.assertTrue(len(warnings_bad) > 0)

    def test_fractional_date_splitting(self) -> None:
        """
        Verifies splitting algorithm for billing cycles that cross monthly boundaries.
        """
        # Bill spanning from May 12 to June 11 (31 days)
        # May contains 20 days (12th to 31st). June contains 11 days (1st to 11th).
        start = date(2026, 5, 12)
        end = date(2026, 6, 11)
        total_qty = Decimal("310.0")

        splits = split_billing_period(start, end, total_qty)

        self.assertEqual(len(splits), 2)
        
        # May split
        self.assertEqual(splits[0]["start_date"], date(2026, 5, 12))
        self.assertEqual(splits[0]["end_date"], date(2026, 5, 31))
        self.assertEqual(splits[0]["allocated_value"], Decimal("200.0"))
        self.assertEqual(splits[0]["days"], 20)

        # June split
        self.assertEqual(splits[1]["start_date"], date(2026, 6, 1))
        self.assertEqual(splits[1]["end_date"], date(2026, 6, 11))
        self.assertEqual(splits[1]["allocated_value"], Decimal("110.0"))
        self.assertEqual(splits[1]["days"], 11)

    def test_sap_strategy_processor(self) -> None:
        """
        Tests the complete pipeline flow for German ERP SAP fuel entries.
        """
        processor = IngestionProcessorFactory.get_processor("sap")

        raw_sap = {
            "WERK": "DE01",
            "MEINS": "LTRS",
            "Menge": "1200,50",
            "Kosten": "1800,45",
            "Buchungsdatum": "15.05.2026",
            "Vehicle_ID": "VEH-7788",
            "Vendor_Name": "Aral Fuel Solutions"
        }

        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="sap",
            raw_data=raw_sap
        )

        activities = processor.process(staging_row)
        self.assertEqual(len(activities), 1)

        act = activities[0]
        self.assertEqual(act.facility, self.facility_hq)
        self.assertEqual(act.quantity, Decimal("1200.50"))
        self.assertEqual(act.unit, "L")
        self.assertEqual(act.cost, Decimal("1800.45"))
        self.assertEqual(act.ghg_scope, "Scope 1")
        self.assertEqual(act.status, "PENDING_REVIEW")

    def test_sap_validation_errors(self) -> None:
        """
        Tests validation error reporting for missing and corrupted Menge (quantity) values.
        """
        processor = IngestionProcessorFactory.get_processor("sap")

        # 1. Test missing Menge (quantity) field
        raw_sap_missing = {
            "WERK": "DE01",
            "MEINS": "LTRS",
            "Buchungsdatum": "15.05.2026",
            "Vehicle_ID": "VEH-7788",
        }
        issues_missing = processor.validate(raw_sap_missing)
        self.assertIn("Missing quantity (Menge) field.", issues_missing)

        # 2. Test whitespace Menge (quantity) field
        raw_sap_whitespace = {
            "WERK": "DE01",
            "MEINS": "LTRS",
            "Menge": "   ",
            "Buchungsdatum": "15.05.2026",
            "Vehicle_ID": "VEH-7788",
        }
        issues_whitespace = processor.validate(raw_sap_whitespace)
        self.assertIn("Missing quantity (Menge) field.", issues_whitespace)

        # 3. Test corrupted non-numeric Menge (quantity) field
        raw_sap_corrupted = {
            "WERK": "DE01",
            "MEINS": "LTRS",
            "Menge": "abc",
            "Buchungsdatum": "15.05.2026",
            "Vehicle_ID": "VEH-7788",
        }
        issues_corrupted = processor.validate(raw_sap_corrupted)
        self.assertIn("Corrupted numerical quantity (Menge) field.", issues_corrupted)

    def test_utility_strategy_processor(self) -> None:
        """
        Tests billing period boundary-splitting logic in Utility Processor strategy.
        """
        processor = IngestionProcessorFactory.get_processor("utility")

        raw_utility = {
            "Facility_Name": "Main HQ Facility",
            "Billing_Period_Start": "2026-05-12",
            "Billing_Period_End": "2026-06-11",
            "Unit": "kWh",
            "kWh_Consumed": "620",
            "Cost": "124,00"
        }

        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="utility",
            raw_data=raw_utility
        )

        activities = processor.process(staging_row)
        self.assertEqual(len(activities), 2)

        # May Split
        may_act = activities[0]
        self.assertEqual(may_act.start_date, date(2026, 5, 12))
        self.assertEqual(may_act.end_date, date(2026, 5, 31))
        self.assertEqual(may_act.quantity, Decimal("400.0"))
        self.assertEqual(may_act.cost, Decimal("80.0"))

        # June Split
        june_act = activities[1]
        self.assertEqual(june_act.start_date, date(2026, 6, 1))
        self.assertEqual(june_act.end_date, date(2026, 6, 11))
        self.assertEqual(june_act.quantity, Decimal("220.0"))
        self.assertEqual(june_act.cost, Decimal("44.0"))

    def test_travel_strategy_processor(self) -> None:
        """
        Tests Scope 3 Corporate Travel strategy with Webhook simulation and flight calculations.
        """
        processor = IngestionProcessorFactory.get_processor("travel")

        # Webhook payload representation (Direct Flight from San Francisco to Paris)
        raw_travel = {
            "Employee_ID": "EMP-4992",
            "Travel_Type": "Flight",
            "Travel_Date": "2026-05-20",
            "From_Airport": "SFO",
            "To_Airport": "CDG",
            "Cabin_Class": "Business",
            "Cost": "2850"
        }

        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="travel",
            raw_data=raw_travel
        )

        activities = processor.process(staging_row)
        self.assertEqual(len(activities), 1)

        act = activities[0]
        self.assertEqual(act.ghg_scope, "Scope 3")
        self.assertEqual(act.unit, "km")
        # SFO -> CDG distance is ~8,960 km
        self.assertAlmostEqual(float(act.quantity), 8960.0, delta=100.0)
        self.assertEqual(act.activity_metadata["cabin_class"], "Business")

        # Verify serialized data output has new fields
        from .serializers import NormalizedRowSerializer
        serializer = NormalizedRowSerializer(act)
        norm_data = serializer.data["normalized_data"]
        self.assertEqual(norm_data["cost"], "2850.00")
        self.assertEqual(norm_data["currency"], "EUR")  # default since no currency was provided in raw
        self.assertEqual(norm_data["travel_date"], "2026-05-20")
        self.assertEqual(norm_data["from_airport"], "SFO")
        self.assertEqual(norm_data["to_airport"], "CDG")

    def test_travel_ground_transport(self) -> None:
        """
        Tests Scope 3 Corporate Travel strategy with ground transport (train/car).
        """
        processor = IngestionProcessorFactory.get_processor("travel")

        raw_ground = {
            "Employee_ID": "EMP-1122",
            "Travel_Type": "Train",
            "Travel_Date": "2026-05-22",
            "Distance": "120.5",
            "Distance_Unit": "Miles",
            "Cost": "85.50",
            "Vehicle_Type": "High-Speed Rail",
            "Fuel_Type": "Electricity"
        }

        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="travel",
            raw_data=raw_ground
        )

        activities = processor.process(staging_row)
        self.assertEqual(len(activities), 1)

        act = activities[0]
        self.assertEqual(act.ghg_scope, "Scope 3")
        self.assertEqual(act.unit, "km")
        # 120.5 Miles is ~193.925 km (120.5 * 1.60934)
        self.assertAlmostEqual(float(act.quantity), 193.925, places=2)
        self.assertEqual(act.activity_metadata["transport_mode"], "train")
        self.assertEqual(act.activity_metadata["vehicle_type"], "High-Speed Rail")
        self.assertEqual(act.activity_metadata["fuel_type"], "Electricity")

    def test_travel_hotel(self) -> None:
        """
        Tests hotel travel lodging ingestion and serialization.
        """
        processor = IngestionProcessorFactory.get_processor("travel")

        raw_hotel = {
            "booking_id": "TRV-8829103",
            "employee_id": "EMP-0422",
            "category": "HOTEL",
            "details": {
                "hotel_name": "Hilton London Paddington",
                "country": "GB",
                "room_nights": 4,
                "number_of_rooms": 1
            },
            "spend": 980,
            "currency": "GBP",
            "Travel_Date": "2026-05-28"
        }

        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="travel",
            raw_data=raw_hotel
        )

        activities = processor.process(staging_row)
        self.assertEqual(len(activities), 1)

        act = activities[0]
        self.assertEqual(act.ghg_scope, "Scope 3")
        self.assertEqual(act.unit, "room-nights")
        self.assertEqual(act.quantity, Decimal("4.0"))
        self.assertEqual(act.cost, Decimal("980.00"))
        self.assertEqual(act.currency, "GBP")

        from .serializers import NormalizedRowSerializer
        serializer = NormalizedRowSerializer(act)
        norm_data = serializer.data["normalized_data"]
        self.assertEqual(norm_data["employee_id"], "EMP-0422")
        self.assertEqual(norm_data["travel_type"], "hotel")
        self.assertEqual(norm_data["hotel_name"], "Hilton London Paddington")
        self.assertEqual(norm_data["hotel_nights"], 4)
        self.assertEqual(norm_data["hotel_country"], "GB")
        self.assertEqual(norm_data["hotel_rooms"], 1)

    def test_audit_locking_policy(self) -> None:
        """
        Ensures once an activity row is APPROVED, it is locked and immutable.
        """
        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="sap",
            raw_data={}
        )

        act = NormalizedEmissionActivity.objects.create(
            organization=self.org_alpha,
            staging_row=staging_row,
            ghg_scope="Scope 1",
            activity_type="fuel",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            quantity=Decimal("150.0"),
            unit="L",
            status="PENDING_REVIEW"
        )

        # Modification is permitted during pending review status
        act.quantity = Decimal("180.0")
        act.save()
        self.assertEqual(act.quantity, Decimal("180.0"))

        # Lock record by setting APPROVED
        act.status = "APPROVED"
        act.save()
        self.assertTrue(act.is_locked)

        # Future modifications must raise ValidationError
        with self.assertRaises(ValidationError):
            act.quantity = Decimal("200.0")
            act.save()

        # Attempt to delete must raise ValidationError
        with self.assertRaises(ValidationError):
            act.delete()

    def test_audit_log_constraints(self) -> None:
        """
        Verifies AuditLog records are append-only and strictly immutable.
        """
        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="sap",
            raw_data={}
        )

        act = NormalizedEmissionActivity.objects.create(
            organization=self.org_alpha,
            staging_row=staging_row,
            ghg_scope="Scope 1",
            activity_type="fuel",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            quantity=Decimal("100.0"),
            unit="L"
        )

        log = AuditLog.objects.create(
            activity=act,
            action="UPLOAD",
            comment="Initial load"
        )

        # Edits to AuditLogs must fail
        with self.assertRaises(ValidationError):
            log.comment = "Malicious alteration attempt"
            log.save()

        # Deletions of AuditLogs must fail
        with self.assertRaises(ValidationError):
            log.delete()

    def test_advanced_messy_utility_parser(self) -> None:
        """
        Tests the dynamic semicolon delimiter detection, header normalization (uppercase),
        and parsing of European decimal values and dash-based date formats.
        """
        processor = IngestionProcessorFactory.get_processor("utility")

        raw_row = {
            "ACCOUNT_ID": "ACC-44102-CA",
            "METER_REF": "MTR-9921X",
            "BILL_START": "15.05.2026",
            "BILL_END": "14.06.2026",
            "READ_TYPE": "ACTUAL",
            "ACTIVE_PEAK_KWH": "34000,00",
            "ACTIVE_OFFPEAK_KWH": "55000,00",
            "REACTIVE_KVAH": "9100",
            "DEMAND_KW": "210,0",
            "RATE_CODE": "TOU-8-CRITICAL",
            "TOTAL_CHARGES": "12450,75",
            "CURRENCY": "USD",
            "FACILITY_ID": "FAC-LA-02"
        }

        csv_payload = (
            "ACCOUNT_ID;BILL_START;BILL_END;ACTIVE_PEAK_KWH;ACTIVE_OFFPEAK_KWH;TOTAL_CHARGES;CURRENCY;FACILITY_ID\n"
            "ACC-44102-CA;15.05.2026;14.06.2026;34000,00;55000,00;12450,75;USD;FAC-LA-02"
        )

        parsed_rows = processor.parse_source(csv_payload)
        self.assertEqual(len(parsed_rows), 1)
        self.assertEqual(parsed_rows[0]["ACCOUNT_ID"], "ACC-44102-CA")

        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="utility",
            raw_data=parsed_rows[0]
        )

        activities = processor.process(staging_row)
        self.assertEqual(len(activities), 2)
        
        may_split = activities[0]
        self.assertEqual(may_split.start_date, date(2026, 5, 15))
        self.assertEqual(may_split.end_date, date(2026, 5, 31))
        self.assertAlmostEqual(float(may_split.quantity), 48806.451613, places=2)
        self.assertAlmostEqual(float(may_split.cost), 6827.83, places=2)

    def test_bulk_actions_and_exports(self) -> None:
        """
        Tests the API endpoints for bulk approval, bulk rejection,
        and certified CSV exports for compliance auditors.
        """
        staging_row = StagingRow.objects.create(
            organization=self.org_alpha,
            source_type="sap",
            raw_data={}
        )

        act1 = NormalizedEmissionActivity.objects.create(
            organization=self.org_alpha,
            staging_row=staging_row,
            ghg_scope="Scope 1",
            activity_type="fuel",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            quantity=Decimal("100.0"),
            unit="L"
        )

        act2 = NormalizedEmissionActivity.objects.create(
            organization=self.org_alpha,
            staging_row=staging_row,
            ghg_scope="Scope 2",
            activity_type="electricity",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            quantity=Decimal("200.0"),
            unit="kWh"
        )

        from django.test import Client
        client = Client()

        # 1. Test Bulk Approve
        response = client.post(
            "/api/rows/bulk-approve/",
            data={"row_ids": [act1.id, act2.id]},
            content_type="application/json",
            HTTP_X_TENANT_ID=str(self.org_alpha.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(NormalizedEmissionActivity.objects.get(id=act1.id).status, "APPROVED")
        self.assertEqual(NormalizedEmissionActivity.objects.get(id=act2.id).status, "APPROVED")

        # 2. Test Bulk Reject
        act3 = NormalizedEmissionActivity.objects.create(
            organization=self.org_alpha,
            staging_row=staging_row,
            ghg_scope="Scope 3",
            activity_type="travel",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 1),
            quantity=Decimal("300.0"),
            unit="km"
        )
        response_reject = client.post(
            "/api/rows/bulk-reject/",
            data={"row_ids": [act3.id]},
            content_type="application/json",
            HTTP_X_TENANT_ID=str(self.org_alpha.id)
        )
        self.assertEqual(response_reject.status_code, 200)
        self.assertEqual(NormalizedEmissionActivity.objects.get(id=act3.id).status, "REJECTED")

        # 3. Test Export Normalized CSV
        response_export = client.get(
            "/api/export-normalized/",
            HTTP_X_TENANT_ID=str(self.org_alpha.id)
        )
        self.assertEqual(response_export.status_code, 200)
        self.assertEqual(response_export["Content-Type"], "text/csv")
        content = response_export.content.decode("utf-8")
        self.assertIn("Activity_ID", content)
        self.assertIn("Scope 1", content)

        # 4. Test Export Audit CSV
        response_audit = client.get(
            "/api/export-audit/",
            HTTP_X_TENANT_ID=str(self.org_alpha.id)
        )
        self.assertEqual(response_audit.status_code, 200)
        self.assertEqual(response_audit["Content-Type"], "text/csv")
        audit_content = response_audit.content.decode("utf-8")
        self.assertIn("Log_ID", audit_content)
        self.assertIn("Bulk approved and locked.", audit_content)
