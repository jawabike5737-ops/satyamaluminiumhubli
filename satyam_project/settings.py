from pathlib import Path
import os
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# ========================
# SECURITY
# ========================
# Default to DEBUG=True for local development; production should set DEBUG='False'
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

# SECRET_KEY: prefer env var, fallback to a safe dev key locally
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')

# ALLOWED_HOSTS from env (comma separated). Default fallback as requested:
allowed = os.environ.get('ALLOWED_HOSTS', '.onrender.com')
ALLOWED_HOSTS = [h.strip() for h in allowed.split(',') if h.strip()]

# ========================
# APPLICATIONS
# ========================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

# ========================
# MIDDLEWARE
# ========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ========================
# TEMPLATES
# ========================
ROOT_URLCONF = "satyam_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "satyam_project.wsgi.application"

# ========================
# DATABASE (Supabase / Postgres recommended for production)
# For local development, fall back to SQLite when DATABASE_URL is not set
# ========================
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ========================
# PASSWORD VALIDATION
# ========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ========================
# INTERNATIONALIZATION
# ========================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ========================
# STATIC FILES (VERY IMPORTANT)
# ========================
STATIC_URL = '/static/'

STATICFILES_DIRS = [BASE_DIR / "static"]

STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ========================
# LOGGING: console + file (logs/error.log)
# ========================
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "error.log"),
            "maxBytes": 5_242_880,  # 5MB
            "backupCount": 3,
            "level": "ERROR",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}

# ========================
# DEFAULT PRIMARY KEY (FIX WARNING)
# ========================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
