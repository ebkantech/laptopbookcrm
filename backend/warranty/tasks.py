from celery import shared_task

from .services import send_due_reminders


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_warranty_reminders():
    return send_due_reminders()
