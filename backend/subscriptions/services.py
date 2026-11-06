"""
Whether this installation may use a module today.

States: active -> grace (7 days past the end) -> read_only. With no plan set
yet nothing is limited, so an existing installation keeps working until its
first plan is activated. Data is never touched by any of this.
"""
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from rentals.models import add_months

from . import catalog
from .models import Package, PackagePrice, Subscription, SubscriptionEvent

GRACE_DAYS = 7
REMINDER_DAYS = (7, 3, 1)
NONE, ACTIVE, GRACE, READ_ONLY = "none", "active", "grace", "read_only"
CACHE_KEY = "subscription:current"
CACHE_SECONDS = 60


def clear_cache():
    cache.delete(CACHE_KEY)


def current():
    """(ends_on, modules) of the plan, or None. Read on every API call, so cached briefly."""
    plan = cache.get(CACHE_KEY)
    if plan is None:
        row = Subscription.objects.select_related("package").order_by("-id").first()
        plan = {"ends_on": row.ends_on, "modules": row.package.modules} if row else {}
        cache.set(CACHE_KEY, plan, CACHE_SECONDS)
    return plan or None


def state(today=None):
    plan = current()
    if not plan:
        return NONE
    today = today or timezone.localdate()
    if today < plan["ends_on"]:
        return ACTIVE
    return GRACE if today < plan["ends_on"] + timedelta(days=GRACE_DAYS) else READ_ONLY


def enabled(module):
    """In the plan. Expiry doesn't change this: read-only stops writing, not reading."""
    plan = current()
    return not plan or module in plan["modules"]


def can_write(module=None, today=None):
    """For background jobs that create records or message customers."""
    return state(today) != READ_ONLY and (module is None or enabled(module))


def off_modules():
    return [module for module in catalog.API_PREFIXES if not enabled(module)]


def blocked_module(path):
    """The module outside the plan that this /api/ path belongs to, if any."""
    tail = path[len("/api/"):]
    for module in off_modules():
        for prefix in catalog.API_PREFIXES[module]:
            if tail == prefix or tail.startswith(f"{prefix}/"):
                return module
    return None


def days_left(today=None):
    plan = current()
    return (plan["ends_on"] - (today or timezone.localdate())).days if plan else None


def summary():
    """What staff screens need."""
    plan = current()
    row = Subscription.objects.select_related("package").order_by("-id").first() if plan else None
    return {
        "state": state(),
        "package": row.package.name if row else None,
        "months": row.months if row else None,
        "starts_on": row.starts_on if row else None,
        "ends_on": row.ends_on if row else None,
        "days_left": days_left(),
        "blocked_prefixes": sorted({p for m in off_modules() for p in catalog.PERMISSION_PREFIXES[m]}),
        "modules": [catalog.label(m) for m in plan["modules"]] if plan else [],
    }


def plans():
    return [
        {"key": package.key, "name": package.name, "modules": [catalog.label(m) for m in package.modules],
         "prices": [{"months": price.months, "amount": price.amount} for price in package.prices.all()]}
        for package in Package.objects.prefetch_related("prices")
    ]


@transaction.atomic
def activate(package_key, months, today=None):
    """Start or renew a plan. Renewing the same package early keeps the days left."""
    today = today or timezone.localdate()
    price = PackagePrice.objects.select_related("package").get(package__key=package_key, months=months)
    row = Subscription.objects.select_for_update().order_by("-id").first()
    start = today
    if row and row.package_id == price.package_id and row.ends_on > today:
        start = row.ends_on
    fields = {"package": price.package, "months": months, "amount": price.amount, "ends_on": add_months(start, months)}
    if row:
        for name, value in fields.items():
            setattr(row, name, value)
        row.starts_on = today
        row.save()
        row.events.filter(key__startswith="remind-").delete()
    else:
        row = Subscription.objects.create(starts_on=today, **fields)
    text = f"{price.package.name}, {months} months, Rs {price.amount}, until {row.ends_on}"
    SubscriptionEvent.objects.create(subscription=row, key=f"activated-{timezone.now().timestamp()}", text=text)
    transaction.on_commit(clear_cache)
    return row


def _tell_admins(subject, body):
    from accounts.models import StaffNotification, User
    from crmbook_backend.notify import send_email

    for user in User.objects.filter(is_superuser=True, is_active=True):
        StaffNotification.objects.create(user=user, event_key="subscription", subject=subject, body=body)
        send_email(user.email, subject, body)


def check_expiry(today=None):
    """Daily. Each notice goes once per plan period. Returns the notices sent."""
    today = today or timezone.localdate()
    row = Subscription.objects.order_by("-id").first()
    if not row:
        return []
    left = (row.ends_on - today).days
    now = state(today)
    notice = None
    if now == READ_ONLY:
        notice = ("remind-read-only", "Your CRM is now read-only",
                  "Your subscription has ended and the grace period is over. Renew to start adding records again.")
    elif now == GRACE:
        notice = ("remind-grace", "Your CRM subscription has ended",
                  f"Renew by {row.ends_on + timedelta(days=GRACE_DAYS)} to avoid read-only mode.")
    else:
        due = [day for day in REMINDER_DAYS if left <= day]
        if due:
            notice = (f"remind-{min(due)}", f"Your CRM subscription ends in {left} day{'s' if left != 1 else ''}",
                      f"Your plan ends on {row.ends_on}. Renew to keep working without interruption.")
    if not notice:
        return []
    event, created = SubscriptionEvent.objects.get_or_create(subscription=row, key=notice[0], defaults={"text": notice[1]})
    if not created:
        return []
    _tell_admins(notice[1], notice[2])
    return [notice[0]]
