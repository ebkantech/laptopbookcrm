# Celery is optional until the background worker is set up.
try:
    from .celery import app as celery_app
except ImportError:
    celery_app = None
