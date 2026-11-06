"""
Run with both of these alongside Django (Redis must be running):
    celery -A crmbook_backend worker -l info        (Windows: add --pool=solo)
    celery -A crmbook_backend beat -l info
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crmbook_backend.settings")

app = Celery("crmbook_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.conf.beat_schedule = {
    "subscription-expiry": {"task": "subscriptions.tasks.check_subscription_expiry", "schedule": crontab(hour=8, minute=0)},
    "rent-invoices": {"task": "rentals.tasks.send_rent_invoices", "schedule": crontab(hour=9, minute=0)},
    "warranty-reminders": {"task": "warranty.tasks.send_warranty_reminders", "schedule": crontab(hour=9, minute=30)},
    "ai-staff-index": {"task": "copilot.tasks.refresh_search_index", "schedule": crontab(hour=2, minute=0)},
}
