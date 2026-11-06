from celery import shared_task

from subscriptions import services

from . import llm, search


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def refresh_search_index(self):
    """Finished records are kept, so a retry after a rate limit carries on."""
    if not services.enabled("copilot") or not search.available():
        return "skipped"
    try:
        return search.rebuild()
    except llm.LLMError as exc:
        raise self.retry(exc=exc)
