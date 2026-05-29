# Generated manually to seed initial organization and facilities

from django.db import migrations


def seed_data(apps, schema_editor):
    Organization = apps.get_model("ingestion", "Organization")
    FacilityProfile = apps.get_model("ingestion", "FacilityProfile")

    # Seed Default Organization
    org, created = Organization.objects.get_or_create(
        slug="breathe-esg-default",
        defaults={"name": "Breathe ESG Default Corp"}
    )

    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="DE01",
        defaults={"facility_name": "Berlin Head Office", "location": "Berlin, Germany"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="DE02",
        defaults={"facility_name": "Munich Operations Plant", "location": "Munich, Germany"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="US01",
        defaults={"facility_name": "Chicago Logistics Warehouse", "location": "Chicago, IL, USA"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="1010",
        defaults={"facility_name": "Frankfurt Logistics Hub", "location": "Frankfurt, Germany"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="1020",
        defaults={"facility_name": "Mumbai Operations Plant", "location": "Mumbai, India"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="1030",
        defaults={"facility_name": "Chennai Factory Warehouse", "location": "Chennai, India"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="Delhi Warehouse",
        defaults={"facility_name": "Delhi Warehouse", "location": "Delhi, India"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="Mumbai Plant",
        defaults={"facility_name": "Mumbai Plant", "location": "Mumbai, India"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="Bangalore Office",
        defaults={"facility_name": "Bangalore Office", "location": "Bangalore, India"}
    )
    FacilityProfile.objects.get_or_create(
        organization=org,
        plant_code="Chennai Factory",
        defaults={"facility_name": "Chennai Factory", "location": "Chennai, India"}
    )


def rollback_data(apps, schema_editor):
    Organization = apps.get_model("ingestion", "Organization")
    Organization.objects.filter(slug="breathe-esg-default").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_data, rollback_data),
    ]
