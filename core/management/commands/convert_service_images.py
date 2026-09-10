from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from core.models import Service
from core.utils import optimize_image
from django.db import transaction
import os

class Command(BaseCommand):
    help = 'Convert existing Service.image files to optimized single WEBP files (1920px, q=85)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show actions without modifying files')

    def handle(self, *args, **options):
        dry = options.get('dry_run', False)
        qs = Service.objects.exclude(image__isnull=True).exclude(image__exact='')
        total = qs.count()
        self.stdout.write(f'Found {total} services with images')
        count = 0
        for svc in qs:
            count += 1
            self.stdout.write(f'[{count}/{total}] Processing Service id={svc.id} image={svc.image.name}')
            try:
                # read original file
                if not svc.image:
                    continue
                try:
                    f = svc.image.open('rb')
                    f.seek(0)
                except Exception:
                    self.stdout.write('  Could not open file, skipping')
                    continue

                optimized = optimize_image(svc.image.file, max_width=1920, quality=85, fmt='WEBP', method=6)
                if not optimized:
                    self.stdout.write('  Optimization failed, skipping')
                    continue

                base = os.path.basename(svc.image.name).rsplit('.', 1)[0]
                new_name = base + '.webp'

                if dry:
                    self.stdout.write(f'  Would save {new_name} (dry-run)')
                    continue

                # Save new optimized file
                svc.image.save(new_name, optimized, save=False)
                svc.save()
                self.stdout.write('  Saved optimized WEBP and updated model')
            except Exception as e:
                self.stderr.write(f'  Error processing service {svc.id}: {e}')
        self.stdout.write('Done')
