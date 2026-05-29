from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError


class Organization(models.Model):
    """
    Represents an enterprise tenant. All raw and normalized data is scoped under an Organization.
    """
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class FacilityProfile(models.Model):
    """
    Maps cryptic plant codes (e.g., SAP WERKS) to facility names and physical locations.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="facilities"
    )
    facility_name = models.CharField(max_length=255)
    plant_code = models.CharField(max_length=50)
    location = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("organization", "plant_code")

    def __str__(self) -> str:
        return f"{self.facility_name} ({self.plant_code})"


class UploadedFile(models.Model):
    """
    Metadata for source file uploads. Tracks file name, source type, and who uploaded it.
    """
    SOURCE_CHOICES = [
        ("sap", "SAP Fuel & Procurement"),
        ("utility", "Utility Electricity Data"),
        ("travel", "Corporate Travel")
    ]
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="uploaded_files"
    )
    source_type = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    original_filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.source_type})"


class StagingRow(models.Model):
    """
    An immutable staging table that stores messy raw ingestion data exactly as it arrived.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="staging_rows"
    )
    uploaded_file = models.ForeignKey(
        UploadedFile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rows"
    )
    source_type = models.CharField(max_length=50)
    raw_data = models.JSONField()
    is_processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            raise ValidationError("StagingRow records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        raise ValidationError("StagingRow records are immutable and cannot be deleted.")

    def __str__(self) -> str:
        return f"StagingRow {self.id} ({self.source_type})"


class NormalizedEmissionActivity(models.Model):
    """
    Canonical emission activities normalized, validated, and categorized by GHG Protocol Scope.
    """
    STATUS_CHOICES = [
        ("PENDING_REVIEW", "Pending Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("FLAGGED", "Flagged"),
    ]

    SCOPE_CHOICES = [
        ("Scope 1", "Scope 1 - Direct Emissions"),
        ("Scope 2", "Scope 2 - Indirect Emissions (Electricity)"),
        ("Scope 3", "Scope 3 - Indirect Travel & Hotel")
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="emission_activities"
    )
    staging_row = models.ForeignKey(
        StagingRow,
        on_delete=models.CASCADE,
        related_name="normalized_activities"
    )

    ghg_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    activity_type = models.CharField(max_length=50)  # e.g., 'fuel', 'electricity', 'travel'
    facility = models.ForeignKey(
        FacilityProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities"
    )

    start_date = models.DateField()
    end_date = models.DateField()

    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    unit = models.CharField(max_length=50)

    cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default="EUR")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING_REVIEW")
    validation_issues = models.JSONField(default=list, blank=True)
    is_locked = models.BooleanField(default=False)

    # Historical snap-shots of original values (to track manual edits)
    original_quantity = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    original_unit = models.CharField(max_length=50, null=True, blank=True)
    original_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    activity_metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError("Start date cannot be after end date.")

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            original = NormalizedEmissionActivity.objects.get(pk=self.pk)
            if original.is_locked:
                raise ValidationError("This record is approved and locked. Modifications are prohibited.")

        if self.status == "APPROVED":
            self.is_locked = True

        # Capture original snapshots at the time of creation
        if not self.pk:
            if self.original_quantity is None:
                self.original_quantity = self.quantity
            if self.original_unit is None:
                self.original_unit = self.unit
            if self.original_cost is None:
                self.original_cost = self.cost

        # Defensively quantize all Decimal fields to match field specifications and prevent ValidationError
        from decimal import Decimal
        if self.quantity is not None:
            self.quantity = Decimal(str(self.quantity)).quantize(Decimal("0.000001"))
        if self.cost is not None:
            self.cost = Decimal(str(self.cost)).quantize(Decimal("0.01"))
        if self.original_quantity is not None:
            self.original_quantity = Decimal(str(self.original_quantity)).quantize(Decimal("0.000001"))
        if self.original_cost is not None:
            self.original_cost = Decimal(str(self.original_cost)).quantize(Decimal("0.01"))

        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        if self.is_locked:
            raise ValidationError("This record is approved and locked. Deletion is prohibited.")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.activity_type} Activity {self.id} ({self.organization.name})"


class AuditLog(models.Model):
    """
    Append-only, immutable audit trail documenting manual edits, overrides, and approvals.
    """
    activity = models.ForeignKey(
        NormalizedEmissionActivity,
        on_delete=models.CASCADE,
        related_name="audit_logs"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    action = models.CharField(max_length=100)  # e.g., 'UPLOAD', 'EDIT', 'APPROVED', 'REJECTED'
    field_modified = models.CharField(max_length=100, null=True, blank=True)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            raise ValidationError("AuditLog records are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("AuditLog records are immutable and cannot be deleted.")

    def __str__(self) -> str:
        return f"AuditLog {self.id} - {self.action} on Activity {self.activity_id}"
