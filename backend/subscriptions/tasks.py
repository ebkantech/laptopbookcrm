from celery import shared_task

from . import services


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def check_subscription_expiry():
    return services.check_expiry()
