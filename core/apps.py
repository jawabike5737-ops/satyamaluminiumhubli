from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Import signal handlers to ensure they are registered when app is loaded
        try:
            from . import signals  # noqa: F401
        except Exception:
            # Avoid raising on import errors during migrations/management commands
            pass
