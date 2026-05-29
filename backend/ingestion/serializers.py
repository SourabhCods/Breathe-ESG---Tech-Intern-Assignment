from rest_framework import serializers
from .models import (
    Organization,
    FacilityProfile,
    UploadedFile,
    StagingRow,
    NormalizedEmissionActivity,
    AuditLog
)


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "created_at"]


class FacilityProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityProfile
        fields = ["id", "organization", "facility_name", "plant_code", "location"]


class AuditLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True, default="System")

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "activity",
            "user",
            "user_username",
            "action",
            "field_modified",
            "old_value",
            "new_value",
            "comment",
            "timestamp"
        ]


class NormalizedRowSerializer(serializers.ModelSerializer):
    """
    Backwards-compatible Serializer mapping NormalizedEmissionActivity to the schema
    expected by the React frontend (NormalizedRow).
    """
    source_type = serializers.CharField(source="activity_type", read_only=True)
    raw_data = serializers.JSONField(source="staging_row.raw_data", read_only=True)
    status = serializers.SerializerMethodField()
    normalized_data = serializers.SerializerMethodField()
    audit_logs = serializers.SerializerMethodField()

    class Meta:
        model = NormalizedEmissionActivity
        fields = [
            "id",
            "organization",
            "staging_row",
            "ghg_scope",
            "activity_type",
            "source_type",
            "facility",
            "start_date",
            "end_date",
            "quantity",
            "unit",
            "cost",
            "currency",
            "status",
            "validation_issues",
            "is_locked",
            "original_quantity",
            "original_unit",
            "original_cost",
            "activity_metadata",
            "raw_data",
            "normalized_data",
            "audit_logs",
            "created_at",
            "updated_at"
        ]
        read_only_fields = [
            "id",
            "organization",
            "staging_row",
            "ghg_scope",
            "activity_type",
            "original_quantity",
            "original_unit",
            "original_cost",
            "is_locked",
            "created_at",
            "updated_at"
        ]

    def get_status(self, obj: NormalizedEmissionActivity) -> str:
        val = obj.status.lower()
        if val == "pending_review":
            return "pending"
        elif val == "flagged":
            return "warning"
        return val

    def get_normalized_data(self, obj: NormalizedEmissionActivity) -> dict:
        meta = obj.activity_metadata
        if obj.activity_type == "fuel":
            return {
                "plant": meta.get("sap_plant_code"),
                "cost": str(obj.cost) if obj.cost else None,
                "unit": obj.unit,
                "vendor": meta.get("vendor_name"),
                "vehicle_id": meta.get("vehicle_id")
            }
        elif obj.activity_type == "electricity":
            return {
                "facility": obj.facility.facility_name if obj.facility else meta.get("sap_plant_code"),
                "billing_start": obj.start_date.isoformat() if obj.start_date else None,
                "billing_end": obj.end_date.isoformat() if obj.end_date else None,
                "consumption_unit": obj.unit,
                "provider": meta.get("provider"),
                "cost": str(obj.cost) if obj.cost else None,
                "currency": obj.currency
            }
        elif obj.activity_type == "travel":
            travel_type = meta.get("raw_travel_type") or ""
            base_data = {
                "employee_id": meta.get("employee_id"),
                "travel_type": travel_type,
                "travel_date": obj.start_date.isoformat() if obj.start_date else None,
                "cost": str(obj.cost) if obj.cost else None,
                "currency": obj.currency,
            }
            if travel_type == "flight":
                base_data.update({
                    "from_airport": meta.get("from_airport"),
                    "to_airport": meta.get("to_airport"),
                    "cabin_class": meta.get("cabin_class"),
                    "carrier": meta.get("carrier") or "",
                    "distance_km": meta.get("calculated_great_circle_km") or float(obj.quantity)
                })
            elif travel_type == "hotel":
                base_data.update({
                    "hotel_name": meta.get("hotel_name"),
                    "hotel_city": meta.get("hotel_city"),
                    "hotel_country": meta.get("hotel_country") or "",
                    "hotel_nights": meta.get("hotel_nights"),
                    "hotel_rooms": meta.get("hotel_rooms") or 1
                })
            elif travel_type in ["ground", "car", "train", "rail", "taxi"]:
                base_data.update({
                    "transport_mode": meta.get("transport_mode") or travel_type,
                    "vehicle_type": meta.get("vehicle_type"),
                    "fuel_type": meta.get("fuel_type"),
                    "distance_km": float(obj.quantity)
                })
            return base_data
        return {}

    def get_audit_logs(self, obj: NormalizedEmissionActivity) -> list:
        logs = obj.audit_logs.all().order_by("-timestamp")
        return AuditLogSerializer(logs, many=True).data
