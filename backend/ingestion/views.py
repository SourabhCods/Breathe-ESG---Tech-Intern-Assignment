from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.request import Request
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal

from .models import (
    Organization,
    StagingRow,
    NormalizedEmissionActivity,
    AuditLog,
    UploadedFile
)
from .serializers import NormalizedRowSerializer
from .services import IngestionProcessorFactory


def get_tenant_organization(request: Request) -> Organization:
    """
    Strictly verifies and extracts the tenant Organization from request context.
    Fails immediately with a ValidationError if the tenant identifier is missing or invalid.
    """
    tenant_id = (
        request.headers.get("X-Tenant-ID") or
        request.query_params.get("tenant_id") or
        request.data.get("tenant_id")
    )
    if not tenant_id:
        raise ValidationError(
            "Multi-tenancy policy violation: Explicit organization identifier "
            "('X-Tenant-ID' header or parameter) is required."
        )

    try:
        # Check if ID is integer
        if str(tenant_id).isdigit():
            return Organization.objects.get(id=int(tenant_id))
        else:
            return Organization.objects.get(slug=str(tenant_id).strip())
    except Organization.DoesNotExist:
        raise ValidationError(
            f"Multi-tenancy violation: Organization '{tenant_id}' does not exist."
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def upload_csv(request: Request) -> Response:
    """
    Ingestion endpoint handling file uploads (CSV/Semicolon CSV) or direct JSON webhook payloads.
    Resolves processor Strategy, creates immutable StagingRow, and saves Normalized records.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    source_type = request.data.get("source_type") or request.POST.get("source_type")
    if not source_type:
        return Response({"error": "Missing parameter 'source_type'"}, status=400)

    try:
        processor = IngestionProcessorFactory.get_processor(source_type)
    except ValueError as val_err:
        return Response({"error": str(val_err)}, status=400)

    file = request.FILES.get("file")
    raw_payloads = []
    uploaded_file = None

    with transaction.atomic():
        if file:
            try:
                # Decoded raw file content
                file_content = file.read().decode("utf-8")
            except UnicodeDecodeError:
                return Response({"error": "File decoding failed. Only UTF-8 format supported."}, status=400)

            # Metadata tracking
            uploaded_file = UploadedFile.objects.create(
                organization=organization,
                source_type=source_type,
                original_filename=file.name,
                uploaded_by=request.user if request.user.is_authenticated else None
            )

            # Let Strategy parse its specific layout (semicolon vs comma, etc.)
            try:
                raw_payloads = processor.parse_source(file_content)
            except Exception as e:
                return Response({"error": f"Failed to parse source file: {str(e)}"}, status=400)
        else:
            # Check for direct JSON body payload (Webhook)
            webhook_data = request.data.get("payload") or request.data
            if not webhook_data or (isinstance(webhook_data, dict) and "source_type" in webhook_data and len(webhook_data) == 1):
                return Response({"error": "No file uploaded and no JSON payload provided."}, status=400)
            
            # Remove metadata fields if nested
            if isinstance(webhook_data, dict) and "payload" in webhook_data:
                webhook_data = webhook_data["payload"]

            try:
                raw_payloads = processor.parse_source(webhook_data)
            except Exception as e:
                return Response({"error": f"Failed to parse JSON payload: {str(e)}"}, status=400)

        created_activities_count = 0
        
        for raw_row in raw_payloads:
            # Skip empty records
            if not raw_row or not any(raw_row.values()):
                continue

            # Create immutable raw staging row
            staging_row = StagingRow.objects.create(
                organization=organization,
                uploaded_file=uploaded_file,
                source_type=source_type,
                raw_data=raw_row
            )

            # Execute Strategy pipeline normalization
            activities = processor.process(staging_row)
            created_activities_count += len(activities)

            # Create audit trail logs for initial upload
            for activity in activities:
                AuditLog.objects.create(
                    activity=activity,
                    user=request.user if request.user.is_authenticated else None,
                    action="UPLOAD",
                    comment=f"Ingested from source: {uploaded_file.original_filename if uploaded_file else 'JSON Webhook'}"
                )

    return Response({
        "message": "Source ingested and normalized successfully.",
        "rows_processed": len(raw_payloads),
        "activities_created": created_activities_count
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def get_rows(request: Request) -> Response:
    """
    Retrieves normalized emission activities scoped strictly to the tenant organization.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    rows = NormalizedEmissionActivity.objects.filter(
        organization=organization
    ).order_by("-created_at")

    # Optional status filtering
    status_filter = request.query_params.get("status")
    if status_filter:
        rows = rows.filter(status=status_filter)

    # Optional source type filtering
    source_filter = request.query_params.get("source_type")
    if source_filter:
        rows = rows.filter(activity_type=source_filter)

    serializer = NormalizedRowSerializer(rows, many=True)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([AllowAny])
def approve_row(request: Request, row_id: int) -> Response:
    """
    Approves a normalized row, locking it permanently against future modifications.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    try:
        activity = NormalizedEmissionActivity.objects.get(id=row_id, organization=organization)
    except NormalizedEmissionActivity.DoesNotExist:
        return Response({"error": f"Record {row_id} not found under tenant."}, status=404)

    if activity.is_locked:
        return Response({"error": "This record is approved and locked. Modifications are prohibited."}, status=400)

    with transaction.atomic():
        activity.status = "APPROVED"
        activity.save()  # sets is_locked = True

        AuditLog.objects.create(
            activity=activity,
            user=request.user if request.user.is_authenticated else None,
            action="APPROVED",
            comment="Record approved and locked for auditors."
        )

    return Response({"message": f"Record {row_id} approved and locked successfully."})


@api_view(["POST"])
@permission_classes([AllowAny])
def reject_row(request: Request, row_id: int) -> Response:
    """
    Rejects a normalized row.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    try:
        activity = NormalizedEmissionActivity.objects.get(id=row_id, organization=organization)
    except NormalizedEmissionActivity.DoesNotExist:
        return Response({"error": f"Record {row_id} not found under tenant."}, status=404)

    if activity.is_locked:
        return Response({"error": "This record is approved and locked. Modifications are prohibited."}, status=400)

    with transaction.atomic():
        activity.status = "REJECTED"
        activity.save()

        AuditLog.objects.create(
            activity=activity,
            user=request.user if request.user.is_authenticated else None,
            action="REJECTED",
            comment="Record rejected by analyst review."
        )

    return Response({"message": f"Record {row_id} rejected."})


@api_view(["POST", "PUT", "PATCH"])
@permission_classes([AllowAny])
def edit_row(request: Request, row_id: int) -> Response:
    """
    Allows analysts to manually override activity attributes (quantity, unit, cost, start_date, end_date).
    Records detailed old/new snapshots to the append-only AuditLog.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    try:
        activity = NormalizedEmissionActivity.objects.get(id=row_id, organization=organization)
    except NormalizedEmissionActivity.DoesNotExist:
        return Response({"error": f"Record {row_id} not found under tenant."}, status=404)

    if activity.is_locked:
        return Response({"error": "This record is approved and locked. Modifications are prohibited."}, status=400)

    mutable_fields = ["quantity", "unit", "cost", "start_date", "end_date"]
    comment = request.data.get("comment") or "Analyst manual override."

    updated_fields_count = 0

    with transaction.atomic():
        for field in mutable_fields:
            if field in request.data:
                new_val = request.data[field]
                old_val = getattr(activity, field)

                # Type normalization for comparison
                if field == "quantity":
                    try:
                        new_val_decimal = Decimal(str(new_val))
                    except (ValueError, TypeError):
                        label = "quantity (Menge)" if activity.activity_type == "fuel" else "quantity"
                        return Response({"error": f"Invalid format for {label}: {new_val}"}, status=400)
                    if new_val_decimal != old_val:
                        setattr(activity, field, new_val_decimal)
                        AuditLog.objects.create(
                            activity=activity,
                            user=request.user if request.user.is_authenticated else None,
                            action="EDIT",
                            field_modified=field,
                            old_value=str(old_val),
                            new_value=str(new_val_decimal),
                            comment=comment
                        )
                        updated_fields_count += 1
                elif field == "cost":
                    if new_val is None or str(new_val).strip() == "":
                        new_val_decimal = None
                    else:
                        try:
                            new_val_decimal = Decimal(str(new_val))
                        except (ValueError, TypeError):
                            return Response({"error": f"Invalid format for cost: {new_val}"}, status=400)
                    if new_val_decimal != old_val:
                        setattr(activity, field, new_val_decimal)
                        AuditLog.objects.create(
                            activity=activity,
                            user=request.user if request.user.is_authenticated else None,
                            action="EDIT",
                            field_modified=field,
                            old_value=str(old_val) if old_val else "",
                            new_value=str(new_val_decimal) if new_val_decimal else "",
                            comment=comment
                        )
                        updated_fields_count += 1
                elif field in ["start_date", "end_date"]:
                    # Expect format YYYY-MM-DD
                    from datetime import datetime
                    try:
                        new_val_date = datetime.strptime(str(new_val), "%Y-%m-%d").date()
                    except ValueError:
                        return Response({"error": f"Invalid format for {field}, use YYYY-MM-DD: {new_val}"}, status=400)
                    if new_val_date != old_val:
                        setattr(activity, field, new_val_date)
                        AuditLog.objects.create(
                            activity=activity,
                            user=request.user if request.user.is_authenticated else None,
                            action="EDIT",
                            field_modified=field,
                            old_value=old_val.isoformat() if old_val else "",
                            new_value=new_val_date.isoformat(),
                            comment=comment
                        )
                        updated_fields_count += 1
                else:  # Unit (str)
                    new_val_str = str(new_val).strip()
                    if new_val_str != old_val:
                        setattr(activity, field, new_val_str)
                        AuditLog.objects.create(
                            activity=activity,
                            user=request.user if request.user.is_authenticated else None,
                            action="EDIT",
                            field_modified=field,
                            old_value=str(old_val),
                            new_value=new_val_str,
                            comment=comment
                        )
                        updated_fields_count += 1

        if updated_fields_count > 0:
            # If manually corrected, we reset status from FLAGGED to PENDING_REVIEW if the data is clean
            # We clear validation issues that are resolved, or we let the analyst decide.
            # To be safe, we clear validation issues on manual override, or mark as pending
            activity.status = "PENDING_REVIEW"
            activity.validation_issues = [
                issue for issue in activity.validation_issues
                if "corrected" in issue or "manual" in issue
            ] + [f"Manually overridden fields: {updated_fields_count}"]
            activity.save()

    serializer = NormalizedRowSerializer(activity)
    return Response(serializer.data)


import csv
from django.http import HttpResponse

@api_view(["POST"])
@permission_classes([AllowAny])
def bulk_approve(request: Request) -> Response:
    """
    Approves multiple normalized rows in a single atomic transaction.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    row_ids = request.data.get("row_ids")
    if not row_ids or not isinstance(row_ids, list):
        return Response({"error": "Missing or invalid list parameter 'row_ids'"}, status=400)

    approved_count = 0
    with transaction.atomic():
        activities = NormalizedEmissionActivity.objects.filter(
            id__in=row_ids,
            organization=organization
        )
        for activity in activities:
            if not activity.is_locked:
                activity.status = "APPROVED"
                activity.save()  # sets is_locked = True
                AuditLog.objects.create(
                    activity=activity,
                    user=request.user if request.user.is_authenticated else None,
                    action="APPROVED",
                    comment="Bulk approved and locked."
                )
                approved_count += 1

    return Response({
        "message": f"Successfully approved and locked {approved_count} records.",
        "approved_ids": row_ids
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def bulk_reject(request: Request) -> Response:
    """
    Rejects multiple normalized rows in a single atomic transaction.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return Response({"error": str(err)}, status=400)

    row_ids = request.data.get("row_ids")
    if not row_ids or not isinstance(row_ids, list):
        return Response({"error": "Missing or invalid list parameter 'row_ids'"}, status=400)

    rejected_count = 0
    with transaction.atomic():
        activities = NormalizedEmissionActivity.objects.filter(
            id__in=row_ids,
            organization=organization
        )
        for activity in activities:
            if not activity.is_locked:
                activity.status = "REJECTED"
                activity.save()
                AuditLog.objects.create(
                    activity=activity,
                    user=request.user if request.user.is_authenticated else None,
                    action="REJECTED",
                    comment="Bulk rejected."
                )
                rejected_count += 1

    return Response({
        "message": f"Successfully rejected {rejected_count} records.",
        "rejected_ids": row_ids
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def export_audit_trail_csv(request: Request) -> HttpResponse:
    """
    Generates a certified CSV report containing the complete audit logs of modifications and reviews.
    Ready to be sent to external sustainability compliance auditors.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return HttpResponse(str(err), status=400, content_type="text/plain")

    # Set up HTTP Response with CSV headers
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="audit_trail_{organization.slug}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Log_ID",
        "Activity_ID",
        "GHG_Scope",
        "Activity_Type",
        "Action",
        "Field_Modified",
        "Old_Value",
        "New_Value",
        "Uploader_Username",
        "Timestamp",
        "Comment"
    ])

    logs = AuditLog.objects.filter(
        activity__organization=organization
    ).order_by("-timestamp")

    for log in logs:
        writer.writerow([
            log.id,
            log.activity.id,
            log.activity.ghg_scope,
            log.activity.activity_type,
            log.action,
            log.field_modified or "N/A",
            log.old_value or "N/A",
            log.new_value or "N/A",
            log.user.username if log.user else "System",
            log.timestamp.isoformat(),
            log.comment or ""
        ])

    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def export_normalized_ledger_csv(request: Request) -> HttpResponse:
    """
    Generates a CSV report of all normalized emission activity records for tenant compliance audit.
    """
    try:
        organization = get_tenant_organization(request)
    except ValidationError as err:
        return HttpResponse(str(err), status=400, content_type="text/plain")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="normalized_ledger_{organization.slug}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Activity_ID",
        "GHG_Scope",
        "Activity_Type",
        "Facility_Name",
        "Plant_Code",
        "Start_Date",
        "End_Date",
        "Normalized_Quantity",
        "Normalized_Unit",
        "Normalized_Cost",
        "Currency",
        "Status",
        "Original_Quantity",
        "Original_Unit",
        "Original_Cost",
        "Is_Locked",
        "Created_At"
    ])

    activities = NormalizedEmissionActivity.objects.filter(
        organization=organization
    ).order_by("-created_at")

    for act in activities:
        writer.writerow([
            act.id,
            act.ghg_scope,
            act.activity_type,
            act.facility.facility_name if act.facility else "N/A",
            act.facility.plant_code if act.facility else "N/A",
            act.start_date.isoformat(),
            act.end_date.isoformat(),
            str(act.quantity),
            act.unit,
            str(act.cost) if act.cost else "N/A",
            act.currency,
            act.status,
            str(act.original_quantity) if act.original_quantity is not None else "N/A",
            act.original_unit or "N/A",
            str(act.original_cost) if act.original_cost is not None else "N/A",
            str(act.is_locked),
            act.created_at.isoformat()
        ])

    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request: Request) -> Response:
    """
    Returns system diagnostic details for verifying ALLOWED_HOSTS and request routing.
    """
    from django.conf import settings
    return Response({
        "status": "ok",
        "debug": settings.DEBUG,
        "allowed_hosts": settings.ALLOWED_HOSTS,
        "host": request.get_host(),
        "x_forwarded_host": request.headers.get("X-Forwarded-Host"),
    })
