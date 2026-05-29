from abc import ABC, abstractmethod
from typing import List, Dict, Any
from ..models import StagingRow, NormalizedEmissionActivity


class BaseIngestionProcessor(ABC):
    """
    Abstract base Strategy for sustainability data processing.
    Handles orchestration of validation, normalization, and insertion.
    """

    @abstractmethod
    def validate(self, raw_data: Dict[str, Any]) -> List[str]:
        """
        Validates the raw data. Returns a list of issues found.
        """
        pass

    @abstractmethod
    def normalize(self, raw_data: Dict[str, Any], organization_id: int) -> List[Dict[str, Any]]:
        """
        Normalizes raw attributes into structured canonical formats.
        Returns a list of dicts (can split one row into multiple calendar months).
        """
        pass

    @abstractmethod
    def get_ghg_scope(self) -> str:
        """
        Returns the Greenhouse Gas Protocol Scope (Scope 1, 2, or 3).
        """
        pass

    @abstractmethod
    def get_activity_type(self) -> str:
        """
        Returns the activity category name.
        """
        pass

    def process(self, staging_row: StagingRow) -> List[NormalizedEmissionActivity]:
        """
        Orchestrates pipeline execution for a staging row.
        """
        raw_data = staging_row.raw_data
        
        # 1. Run global row validations
        validation_issues = self.validate(raw_data)

        # 2. Normalize and split if necessary
        try:
            normalized_records = self.normalize(raw_data, staging_row.organization_id)
        except Exception as e:
            # Fallback error mapping to prevent crashes on completely corrupted records
            normalized_records = [{
                "start_date": None,
                "end_date": None,
                "quantity": 0.0,
                "unit": "UNKNOWN",
                "cost": None,
                "currency": "EUR",
                "validation_issues": [f"Critical processing error: {str(e)}"]
            }]

        activities = []
        for record in normalized_records:
            # Combine generic issues and record-specific issues
            record_issues = list(validation_issues)
            if "validation_issues" in record:
                record_issues.extend(record["validation_issues"])

            # Filter out empty issue strings
            record_issues = [issue for issue in record_issues if issue]

            # If dates are missing or invalid, flag
            start_date = record.get("start_date")
            end_date = record.get("end_date")
            if not start_date or not end_date:
                record_issues.append("Missing or invalid start/end dates.")

            status = "FLAGGED" if record_issues else "PENDING_REVIEW"

            # Create Normalized record
            activity = NormalizedEmissionActivity(
                organization=staging_row.organization,
                staging_row=staging_row,
                ghg_scope=self.get_ghg_scope(),
                activity_type=self.get_activity_type(),
                facility=record.get("facility"),
                start_date=start_date if start_date else date_fallback(),
                end_date=end_date if end_date else date_fallback(),
                quantity=record.get("quantity", 0.0),
                unit=record.get("unit", "UNKNOWN"),
                cost=record.get("cost"),
                currency=record.get("currency", "EUR"),
                status=status,
                validation_issues=record_issues,
                activity_metadata=record.get("activity_metadata", {})
            )
            activity.save()
            activities.append(activity)

        # Bypasses pk check in StagingRow.save()
        StagingRow.objects.filter(pk=staging_row.pk).update(is_processed=True)
        return activities


def date_fallback() -> Any:
    # A safe date fallback for database validation constraints
    import datetime
    return datetime.date(2000, 1, 1)
