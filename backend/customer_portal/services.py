import secrets
from datetime import datetime, timedelta, time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from rentals.models import Rental, RentalEvent
from repairs.models import RepairTicket, RepairTicketEvent

from .models import CustomerAccessToken, CustomerMembership, CustomerProfile
from .utils import normalize_phone, token_hash


def _unique_username(phone_e164):
    User = get_user_model()
    stem = f"customer_{phone_e164.lstrip('+')}"
    username = stem
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{stem}_{suffix}"
    return username


@transaction.atomic
def get_or_create_customer_profile(party, created_by, phone=None):
    existing = party.portal_memberships.select_related("profile__user").order_by("-is_primary", "id").first()
    if existing:
        return existing.profile, False

    phone_e164 = normalize_phone(phone or party.phone)
    profile = CustomerProfile.objects.select_related("user").filter(phone_e164=phone_e164).first()
    created = False
    if profile is None:
        User = get_user_model()
        user = User.objects.create_user(
            username=_unique_username(phone_e164),
            email=party.email,
            first_name=party.name[:150],
            phone=phone_e164,
            is_staff=False,
            is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        profile = CustomerProfile.objects.create(
            user=user,
            phone_e164=phone_e164,
            created_by=created_by,
        )
        created = True
    CustomerMembership.objects.get_or_create(
        profile=profile,
        party=party,
        defaults={"role": CustomerMembership.OWNER, "is_primary": not profile.memberships.exists()},
    )
    return profile, created


@transaction.atomic
def issue_access_token(profile, purpose, created_by):
    if purpose == CustomerAccessToken.ACTIVATION and profile.status == CustomerProfile.ACTIVE:
        raise ValidationError({"detail": "This customer account is already active. Generate a password-reset link instead."})
    if purpose == CustomerAccessToken.PASSWORD_RESET and profile.status != CustomerProfile.ACTIVE:
        raise ValidationError({"detail": "Activate this customer account before generating a password-reset link."})

    now = timezone.now()
    profile.access_tokens.filter(
        purpose=purpose,
        consumed_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)
    raw_token = secrets.token_urlsafe(32)
    hours = int(getattr(settings, "CUSTOMER_PORTAL_TOKEN_HOURS", 24))
    token = CustomerAccessToken.objects.create(
        profile=profile,
        purpose=purpose,
        token_hash=token_hash(raw_token),
        expires_at=now + timedelta(hours=hours),
        created_by=created_by,
    )
    route = "activate" if purpose == CustomerAccessToken.ACTIVATION else "reset-password"
    url = f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/customer/{route}/{raw_token}"
    return token, url


def get_access_token(raw_token, purpose, for_update=False):
    if not raw_token or len(raw_token) > 200:
        raise NotFound("This secure link is invalid or has expired.")
    queryset = CustomerAccessToken.objects.select_related("profile__user").prefetch_related(
        "profile__memberships__party"
    )
    if for_update:
        queryset = queryset.select_for_update()
    try:
        token = queryset.get(token_hash=token_hash(raw_token), purpose=purpose)
    except CustomerAccessToken.DoesNotExist as exc:
        raise NotFound("This secure link is invalid or has expired.") from exc
    if not token.is_usable:
        raise NotFound("This secure link is invalid or has expired.")
    return token


def _aware_date(value):
    return timezone.make_aware(datetime.combine(value, time.max), timezone.get_current_timezone())


def access_summary(profile):
    party_ids = list(profile.memberships.values_list("party_id", flat=True))
    now = timezone.now()
    grace_days = int(getattr(settings, "CUSTOMER_PORTAL_GRACE_DAYS", 30))

    active_rentals = Rental.objects.filter(party_id__in=party_ids).exclude(
        status__in=[Rental.REJECTED, Rental.CLOSED, Rental.CANCELLED]
    ).count()
    active_repairs = RepairTicket.objects.filter(party_id__in=party_ids).exclude(
        status=RepairTicket.DELIVERED
    ).count()
    if active_rentals or active_repairs:
        return {
            "mode": "active",
            "can_decide": True,
            "active_rentals": active_rentals,
            "active_repairs": active_repairs,
            "access_until": None,
        }

    activity_candidates = [profile.activated_at or profile.created_at]
    rental_event_at = RentalEvent.objects.filter(rental__party_id__in=party_ids).aggregate(value=Max("at"))["value"]
    repair_event_at = RepairTicketEvent.objects.filter(ticket__party_id__in=party_ids).aggregate(value=Max("at"))["value"]
    latest_rental_date = Rental.objects.filter(party_id__in=party_ids).aggregate(value=Max("last_payment"))["value"]
    latest_repair_date = RepairTicket.objects.filter(party_id__in=party_ids).aggregate(value=Max("received"))["value"]
    activity_candidates.extend(value for value in [rental_event_at, repair_event_at] if value)
    activity_candidates.extend(_aware_date(value) for value in [latest_rental_date, latest_repair_date] if value)
    latest_activity = max(activity_candidates)
    access_until = latest_activity + timedelta(days=grace_days)
    mode = "read_only" if now <= access_until else "expired"
    return {
        "mode": mode,
        "can_decide": False,
        "active_rentals": 0,
        "active_repairs": 0,
        "access_until": access_until,
    }
