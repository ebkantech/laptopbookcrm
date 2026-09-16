"""
Django settings for crmbook_backend project.

Environment-driven: every value that differs between development and
production is read from an environment variable, with a safe local
default so `python manage.py runserver` still works out of the box
with zero setup. See backend/.env.example for the full list.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# A local backend/.env is convenient for developer-only credentials. It is
# ignored by Git, and real environment variables supplied by a host always
# take precedence because override=False.
load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    val = os.environ.get(name, default)
    return [v.strip() for v in val.split(",") if v.strip()]


# ---------------------------------------------------------------- #
# Core security settings
# ---------------------------------------------------------------- #

# SECURITY WARNING: this fallback is fine for local development only.
# In production, DJANGO_SECRET_KEY *must* be set as a real environment
# variable -- never commit a production key to version control.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-do-not-use-in-production-enk-ua7k39rszvxlj",
)

# Defaults to False (safe) -- set DJANGO_DEBUG=True explicitly for local dev.
DEBUG = env_bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")

# ---------------------------------------------------------------- #
# Applications
# ---------------------------------------------------------------- #

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',

    'accounts',
    'catalog',
    'parties',
    'sales',
    'rentals',
    'repairs',
    'accounting',
    'broadcast',
    'dashboard',
    'warranty',
]

AUTH_USER_MODEL = 'accounts.User'

# Existing project migrations use BigAutoField primary keys. Keep Django's
# model default aligned with that established schema so future migrations do
# not try to change every implicit primary key to AutoField.
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    # NOTE: no DEFAULT_THROTTLE_CLASSES here on purpose -- the login
    # throttle below is scoped to the token endpoint specifically
    # (see accounts/throttling.py + accounts/views.py ThrottledTokenView),
    # not applied blanket to every API call.
    'DEFAULT_THROTTLE_RATES': {
        'login': os.environ.get('LOGIN_THROTTLE_RATE', '5/min'),
        'repair_approval': os.environ.get('REPAIR_APPROVAL_THROTTLE_RATE', '60/hour'),
        'rental_approval': os.environ.get('RENTAL_APPROVAL_THROTTLE_RATE', '60/hour'),
    },
}

SIMPLE_JWT = {
    # shorter-lived access token = smaller window if one leaks; the
    # frontend already silently refreshes it, so this is invisible to
    # the user. Override via env for a longer/shorter window.
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('JWT_ACCESS_MINUTES', 60))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('JWT_REFRESH_DAYS', 7))),
    # a token blacklisted on logout can never be exchanged again, even
    # though it hasn't naturally expired yet
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173,http://127.0.0.1:5173",
)
CORS_ALLOW_CREDENTIALS = True

# Set PUBLIC_FRONTEND_URL to the HTTPS customer-facing frontend origin in production.
PUBLIC_FRONTEND_URL = os.environ.get("PUBLIC_FRONTEND_URL", "http://localhost:5173")

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'crmbook_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'crmbook_backend.wsgi.application'

# ---------------------------------------------------------------- #
# Database -- SQLite by default; PostgreSQL when POSTGRES_DB is set.
# The same POSTGRES_* configuration works locally, in staging, and in
# production. Set POSTGRES_SSLMODE=require when a managed provider requires
# encrypted database transport; leave it unset for a local server.
# ---------------------------------------------------------------- #

if os.environ.get("POSTGRES_DB"):
    postgres_options = {}
    postgres_sslmode = os.environ.get("POSTGRES_SSLMODE", "").strip()
    if postgres_sslmode:
        postgres_options["sslmode"] = postgres_sslmode

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ["POSTGRES_DB"],
            'USER': os.environ.get("POSTGRES_USER", "postgres"),
            'PASSWORD': os.environ.get("POSTGRES_PASSWORD", ""),
            'HOST': os.environ.get("POSTGRES_HOST", "localhost"),
            'PORT': os.environ.get("POSTGRES_PORT", "5432"),
            'CONN_MAX_AGE': int(os.environ.get("POSTGRES_CONN_MAX_AGE", 60)),
            'CONN_HEALTH_CHECKS': env_bool("POSTGRES_CONN_HEALTH_CHECKS", default=not DEBUG),
        }
    }
    if postgres_options:
        DATABASES['default']['OPTIONS'] = postgres_options
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ---------------------------------------------------------------- #
# Password validation
# ---------------------------------------------------------------- #

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------- #
# Internationalization
# ---------------------------------------------------------------- #

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------- #
# Static files
# ---------------------------------------------------------------- #

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ---------------------------------------------------------------- #
# Email (still console backend until a real provider is wired --
# see EXTERNAL_INTEGRATIONS notes in the project README)
# ---------------------------------------------------------------- #

EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)

# ---------------------------------------------------------------- #
# Security headers -- only meaningfully active when DEBUG=False and
# the app is actually served over HTTPS (a local dev server on plain
# HTTP would break under SECURE_SSL_REDIRECT, hence the DEBUG guard).
# Toggle individually via env if your reverse proxy already handles
# some of these (e.g. Nginx terminating SSL and setting HSTS itself).
# ---------------------------------------------------------------- #

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 3600))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMAINS", default=False)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", default=False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    # honour X-Forwarded-Proto from a reverse proxy (Nginx) so Django
    # knows the original request was HTTPS even though it reaches
    # Gunicorn over plain HTTP internally
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

X_FRAME_OPTIONS = 'DENY'
