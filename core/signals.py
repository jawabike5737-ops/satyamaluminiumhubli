import logging
import os
from django.conf import settings
from django.db import transaction
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from django.core.files.storage import default_storage

from .models import Service

logger = logging.getLogger(__name__)


def _is_deletable_media(path):
    if not path:
        return False
    # Normalize
    name = os.path.basename(path).lower()
    # Never delete obvious placeholders or default files
    if 'default' in name or 'placeholder' in name:
        return False
    # Skip static references
    if path.startswith('static/') or path.startswith(settings.STATIC_URL or ''):
        return False
    return True


def _safe_delete(path, instance_pk=None):
    try:
        if not path or not _is_deletable_media(path):
            return False

        # Ensure no other DB object references this file (avoid accidental shared deletions)
        referenced = Service.objects.filter(image=path)
        if instance_pk is not None:
            referenced = referenced.exclude(pk=instance_pk)
        if referenced.exists():
            logger.debug('File %s still referenced by other objects; skipping delete', path)
            return False

        # Use storage API to delete (works for local and remote backends)
        try:
            if default_storage.exists(path):
                default_storage.delete(path)
                logger.info('Deleted media file: %s', path)
                return True
            else:
                logger.debug('File %s does not exist in storage; skipping', path)
                return False
        except Exception as e:
            logger.exception('Failed to delete media file %s: %s', path, e)
            return False

    except Exception:
        return False


@receiver(pre_save, sender=Service)
def service_pre_save(sender, instance, **kwargs):
    # Detect if image is being replaced. If so, remember old path to delete after successful save
    try:
        if not instance.pk:
            return
        try:
            old = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            return

        old_path = old.image.name if getattr(old, 'image', None) else None
        new_path = instance.image.name if getattr(instance, 'image', None) else None

        if old_path and old_path != new_path and _is_deletable_media(old_path):
            # stash on instance for post_save handling
            instance._old_image_path = old_path
    except Exception as e:
        logger.exception('Error in service_pre_save: %s', e)


@receiver(post_delete, sender=Service)
def service_post_delete(sender, instance, **kwargs):
    # When a Service is deleted, remove its image after DB transaction commit
    try:
        path = instance.image.name if getattr(instance, 'image', None) else None
        if not path or not _is_deletable_media(path):
            return

        def _do_delete():
            _safe_delete(path, instance_pk=instance.pk)

        try:
            transaction.on_commit(_do_delete)
        except Exception:
            # Fallback: try immediate delete but swallow errors
            _do_delete()

    except Exception as e:
        logger.exception('Error in service_post_delete: %s', e)


# Post-save cleanup: we purposely attach via transaction.on_commit to ensure
# the DB transaction succeeded (prevents deleting file when save/transaction rolls back).
def _attach_post_save_cleanup(instance):
    path = getattr(instance, '_old_image_path', None)
    if not path:
        return

    def _do_delete():
        _safe_delete(path, instance_pk=instance.pk)

    try:
        transaction.on_commit(_do_delete)
    except Exception:
        # If on_commit not available or fails, run immediately (best-effort)
        _do_delete()


# Connect post_save dynamically to avoid import cycles
from django.db.models.signals import post_save


@receiver(post_save, sender=Service)
def service_post_save(sender, instance, created, **kwargs):
    # Only attempt to delete old file if we recorded one in pre_save
    try:
        if hasattr(instance, '_old_image_path'):
            _attach_post_save_cleanup(instance)
            try:
                del instance._old_image_path
            except Exception:
                pass
    except Exception as e:
        logger.exception('Error in service_post_save: %s', e)
