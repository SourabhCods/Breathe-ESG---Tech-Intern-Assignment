from django.urls import path
from ingestion.views import (
    upload_csv,
    get_rows,
    approve_row,
    reject_row,
    edit_row
)

urlpatterns = [
    path("api/upload/", upload_csv),
    path("api/rows/", get_rows),
    path("api/rows/<int:row_id>/approve/", approve_row),
    path("api/rows/<int:row_id>/reject/", reject_row),
    path("api/rows/<int:row_id>/edit/", edit_row),
]
