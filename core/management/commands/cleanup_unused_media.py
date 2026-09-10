import os
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage

from core.models import Service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Scan media/services/ and delete files not referenced by any Service.image'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='Actually delete files (default is dry-run)')
        parser.add_argument('--path', default='services', help='Relative media path to scan (default: services)')

    def handle(self, *args, **options):
        do_delete = options.get('yes')
        rel_path = options.get('path')

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            self.stderr.write('MEDIA_ROOT is not configured; aborting.')
            return

        target_dir = os.path.join(media_root, rel_path)
        if not os.path.exists(target_dir):
            self.stdout.write(f'No directory at {target_dir}; nothing to do.')
            return

        # Gather referenced paths from DB
        referenced = set()
        for img in Service.objects.exclude(image__isnull=True).exclude(image__exact='').values_list('image', flat=True):
            if img:
                referenced.add(img)

        deleted_count = 0
        total_found = 0

        for root, dirs, files in os.walk(target_dir):
            for fname in files:
                total_found += 1
                # Compute relative path from MEDIA_ROOT
                full_path = os.path.join(root, fname)
                rel = os.path.relpath(full_path, media_root).replace('\\', '/')

                if rel not in referenced:
                    self.stdout.write(f'Orphan: {rel}')
                    if do_delete:
                        try:
                            default_storage.delete(rel)
                            deleted_count += 1
                            self.stdout.write(f'Deleted orphan image: {rel}')
                        except Exception as e:
                            logger.exception('Failed to delete %s: %s', rel, e)
                else:
                    # referenced
                    pass

        self.stdout.write(f'Found {total_found} files under {rel_path}.')
        if do_delete:
            self.stdout.write(f'Deleted {deleted_count} orphan files.')
        else:
            self.stdout.write('Dry-run mode: use --yes to actually delete files.')
