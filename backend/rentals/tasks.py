from celery import shared_task

from .billing import send_due_rent_invoices


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_rent_invoices():
    """Safe to retry: a period that already has an invoice is skipped."""
    result = send_due_rent_invoices()
    return {"raised": len(result["raised"]), "skipped": len(result["skipped"])}
