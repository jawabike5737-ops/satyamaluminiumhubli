# fix_images.py

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satyam_project.settings")

import django
django.setup()

from core.models import Service
from django.core.files import File

folder = "media/services"

for service in Service.objects.only('id', 'image', 'name'):

    if not service.image:
        continue

    current = os.path.basename(service.image.name)

    matches = []

    for f in os.listdir(folder):
        if service.name.lower().replace(" ", "_")[:10].lower() in f.lower():
            matches.append(f)

    if matches:
        file_name = matches[0]

        with open(os.path.join(folder, file_name), "rb") as img:
            service.image.save(file_name, File(img), save=True)

        print("Fixed:", service.name)