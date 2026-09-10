import os
import django
from django.core.files import File

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satyam_project.settings")
django.setup()

from core.models import Service

uploaded = 0
failed = 0

MEDIA_DIR = os.path.join(os.getcwd(), "media", "services")

for service in Service.objects.only('id', 'image', 'name'):

    if not service.image:
        continue

    try:
        filename = os.path.basename(service.image.name)
        local_path = os.path.join(MEDIA_DIR, filename)

        if not os.path.exists(local_path):
            print(f"Missing: {filename}")
            failed += 1
            continue

        print(f"Uploading: {filename}")

        with open(local_path, "rb") as f:
            service.image.save(
                filename,
                File(f),
                save=True
            )

        uploaded += 1

    except Exception as e:
        print(f"Failed: {filename}")
        print(e)
        failed += 1

print("\n======================")
print(f"Uploaded: {uploaded}")
print(f"Failed: {failed}")
print("======================")