from django.urls import path
from ingestion.views import (
    upload_csv,
    get_rows,
    approve_row,
    reject_row,
    edit_row,
    bulk_approve,
    bulk_reject,
    export_audit_trail_csv,
    export_normalized_ledger_csv
)

urlpatterns = [
    path("api/upload/", upload_csv),
    path("api/rows/", get_rows),
    path("api/rows/<int:row_id>/approve/", approve_row),
    path("api/rows/<int:row_id>/reject/", reject_row),
    path("api/rows/<int:row_id>/edit/", edit_row),
    path("api/rows/bulk-approve/", bulk_approve),
    path("api/rows/bulk-reject/", bulk_reject),
    path("api/export-audit/", export_audit_trail_csv),
    path("api/export-normalized/", export_normalized_ledger_csv),
]
