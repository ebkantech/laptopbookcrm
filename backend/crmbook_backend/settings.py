"""
Django settings for crmbook_backend project.

Environment-driven: every value that differs between development and
production is read from an environment variable, with a safe local
default so `python manage.py runserver` still works out of the box
with zero setup. See backend/.env.example for the full list.
"""

import os
import sys
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
DEBUG = env_bool("DJANGO_DEBUG", default=False)

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
    'portal',
    'reports',
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
        # Task 6 security checklist: brute-force protection on the portal
        # OTP verify step -- see accounts.throttling.OTPVerifyThrottle.
        'otp_verify': os.environ.get('OTP_VERIFY_THROTTLE_RATE', '5/min'),
        # portal "resend code": per IP, and per invitation link
        'otp_resend': os.environ.get('OTP_RESEND_THROTTLE_RATE', '10/hour'),
        'otp_resend_invite': os.environ.get('OTP_RESEND_INVITE_THROTTLE_RATE', '5/hour'),
        # customer portal invoice PDF downloads, per customer
        'portal_pdf': os.environ.get('PORTAL_PDF_THROTTLE_RATE', '60/hour'),
    },
}

# Minimum wait between two portal verification codes for the same link.
PORTAL_OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get('PORTAL_OTP_RESEND_COOLDOWN_SECONDS', 60))
# Fernet key(s) encrypting the short-lived copy of a portal code that
# portal.manage staff can read in the CRM (portal/otp_vault.py). Generate:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Comma-separate keys to rotate (first encrypts). Unset = staff can't see codes.
PORTAL_OTP_ENCRYPTION_KEY = os.environ.get('PORTAL_OTP_ENCRYPTION_KEY', '')

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

# The frontend (staff app + token-based customer portal) is served from one
# Vite origin -- keep this, PUBLIC_FRONTEND_URL and CSRF_TRUSTED_ORIGINS in
# sync if that ever changes.
CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    default="http://localhost:5174,http://127.0.0.1:5174",
) or ["http://localhost:5174", "http://127.0.0.1:5174"]
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default="http://localhost:5174,http://127.0.0.1:5174",
) or ["http://localhost:5174", "http://127.0.0.1:5174"]

# Local Vite development may run on either port. Keep these additions
# development-only, while retaining every origin explicitly configured for
# production (DEBUG=False) and any other environment-specific origins.
if DEBUG:
    local_frontend_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    CORS_ALLOWED_ORIGINS = list(dict.fromkeys([*CORS_ALLOWED_ORIGINS, *local_frontend_origins]))
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, *local_frontend_origins]))

CORS_ALLOW_CREDENTIALS = True
# Lets the portal read throttling waits cross-origin (portal resend/verify 429s).
CORS_EXPOSE_HEADERS = ["Retry-After"]

# Django's own session cookie is used by the admin site (and by
# SessionAuthentication as a DRF fallback) -- hardened regardless, since the
# customer portal itself is stateless (django.core.signing tokens, no
# server-side session; see portal/auth.py).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_COOKIE_AGE", 28800))
CSRF_COOKIE_SAMESITE = "Lax"

# Seller details printed at the top of every sales invoice. Per-branch
# address/phone/GSTIN live on catalog.StockPoint; these are the
# business-wide values (and the GSTIN fallback for branches without one).
BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Vantage Computers")
BUSINESS_GSTIN = os.environ.get("BUSINESS_GSTIN", "")
BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "")
BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "")
# Days a customer has to pay a sale or repair invoice before it's Overdue.
INVOICE_DUE_DAYS = int(os.environ.get("INVOICE_DUE_DAYS", 7))

# Set PUBLIC_FRONTEND_URL to the HTTPS customer-facing frontend origin in production.
PUBLIC_FRONTEND_URL = os.environ.get("PUBLIC_FRONTEND_URL", "http://localhost:5174")

# Task 3: shared secret a WhatsApp Business API provider's delivery-status
# webhook must present (see portal/whatsapp-webhook/) before its
# sent/delivered/read/failed callbacks are trusted. None until a provider
# is actually picked (Task 2) and this is set in the environment -- the
# webhook refuses everything until then, which is the safe default, not
# a bug to "fix" by hardcoding a value here.
WHATSAPP_WEBHOOK_SECRET = os.environ.get("WHATSAPP_WEBHOOK_SECRET")
# Meta's own webhook (portal/meta_webhook.py, api/whatsapp/meta-webhook/):
# the verify token you type into Meta's webhook settings, and the app
# secret Meta signs each delivery-status POST with. Unset = refuse all.
WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET")

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

# Uploaded files (rental handover photos). Never served from a public URL:
# rentals.views streams them to signed-in staff or via a customer's own
# approval link only, so no MEDIA_URL route is registered.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
# Phone camera photos are a few MB; leave headroom for the multipart body.
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# ---------------------------------------------------------------- #
# Email (still console backend until a real provider is wired --
# see EXTERNAL_INTEGRATIONS notes in the project README)
# ---------------------------------------------------------------- #

# SMTP: setting EMAIL_HOST switches to the SMTP backend automatically
# (an explicit DJANGO_EMAIL_BACKEND still wins). Without it, emails are
# only printed to the runserver console.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.environ.get("EMAIL_PORT") or 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
# TLS and SSL are mutually exclusive in Django; SSL (port 465) wins.
EMAIL_USE_TLS = False if EMAIL_USE_SSL else env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT") or 20)

EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER or "no-reply@vantagecomputers.example"

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

# `manage.py test` talks plain HTTP through Django's test client, so the
# HTTPS redirect would answer every API test with a 301. Never true when
# serving real traffic.
if len(sys.argv) > 1 and sys.argv[1] == "test":
    SECURE_SSL_REDIRECT = False

X_FRAME_OPTIONS = 'DENY'
