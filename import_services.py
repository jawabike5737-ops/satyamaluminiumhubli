import json
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satyam_project.settings")
django.setup()

from core.models import Service

with open("services.json", "r", encoding="utf-16") as f:
    services = json.load(f)

for item in services:
    fields = item["fields"]

    try:
        name = fields.get("name", "")

        if Service.objects.filter(name=name).exists():
            continue

        Service.objects.create(
            service_code=fields.get("service_code"),
            name=fields.get("name", ""),
            category=fields.get("category", ""),
            description=fields.get("description", ""),
            default_rate=fields.get("default_rate", 0),
            service_name=fields.get("service_name", ""),
            unit=fields.get("unit", "Sq Ft"),
            image=fields.get("image"),
            status=fields.get("status", "active"),
        )

        print("Added:", name)

    except Exception as e:
        print("\nERROR RECORD:")
        print(fields)
        print("\nERROR:")
        print(e)
        break