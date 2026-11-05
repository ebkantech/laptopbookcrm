"""
Who may use the customer portal, and until when.

Two separate clocks live here and must never be confused:

* the invitation LINK (PortalInvite.expires_at) -- reusable until it
  expires: the end of the rental tenure for Rental customers, 24 hours
  after creation for Dealer/Retail customers;
* the one-time CODE (PortalInvite.otp_expires_at) -- 30 minutes after it
  was emailed, single-use, replaceable from the same link via resend.

Rental entitlement policy: only agreements in Rental.APPROVED or
Rental.ACTIVE count (the same statuses rent can be invoiced against --
see rentals.billing.raise_rent_invoice). Draft, pending, rejected,
cancelled and closed agreements never grant access, and a new agreement
counts only once the customer is verified and the deposit and advance are
paid (rentals.onboarding.portal_ready). When several
qualifying agreements exist the LATEST end wins, so the customer keeps
portal access while any of them is still running.

Repair entitlement policy: for a Dealer/Retail customer the job's status
decides the portal, not the link's own expiry. It stays open while any job is
open, and for 24 hours after a final bill is paid (RepairTicket.portal_until).
A job paid in full in advance has no final payment, so it closes at Delivered.
A job that comes back opens it again. A Rental account follows its rental
while one is running; with none running (closed, expired, never started) a
repair job gives it the same repair-only access as anyone else, so rental
history never blocks a repair.

End-date convention: an agreement covers start .. add_months(start,
tenure) - 1 day inclusive (rentals.billing.next_billing_period bills the
last month up to that day), so access ends at local midnight starting
add_months(start, tenure).
"""
import math
from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from parties.models import Party
from rentals import onboarding
from rentals.models import Rental, add_months
from repairs.models import RepairTicket

OTP_TTL = timedelta(minutes=30)
NON_RENTAL_INVITE_TTL = timedelta(hours=24)
# Only a ceiling: the job's status closes the link long before this.
REPAIR_INVITE_TTL = timedelta(days=90)
MAX_OTP_ATTEMPTS = 5
QUALIFYING_RENTAL_STATUSES = (Rental.APPROVED, Rental.ACTIVE)
CANONICAL_TYPES = {Party.RENTAL, Party.DEALER, Party.RETAIL}
UNKNOWN_TYPE = "Unknown"


def account_type(party):
    """Party.type exactly as stored when it is one of the three real account
    types; anything else is "Unknown" -- never silently Rental (or anything else)."""
    return party.type if party.type in CANONICAL_TYPES else UNKNOWN_TYPE


def resend_cooldown_seconds() -> int:
    return int(getattr(settings, "PORTAL_OTP_RESEND_COOLDOWN_SECONDS", 60))


def rental_end_at(rental):
    """Exclusive end of an agreement: local midnight the day after its last covered day."""
    end_date = add_months(rental.start, rental.tenure_months)
    return timezone.make_aware(datetime.combine(end_date, time.min), timezone.get_current_timezone())


def rental_last_day(rental):
    """Last day the agreement covers (inclusive) -- the day before rental_end_at."""
    return add_months(rental.start, rental.tenure_months) - timedelta(days=1)


def rental_access_ends_at(party, now=None):
    """Latest end among the party's qualifying agreements, or None when none is still running."""
    now = now or timezone.now()
    rentals = Rental.objects.filter(party=party, status__in=QUALIFYING_RENTAL_STATUSES)
    ends = [rental_end_at(r) for r in rentals]
    ends = [end for r, end in zip(rentals, ends) if end > now and onboarding.portal_ready(r)]
    return max(ends) if ends else None


def repair_job_open(party):
    """The customer has a job still in the shop."""
    return RepairTicket.objects.filter(party=party).exclude(status=RepairTicket.DELIVERED).exists()


def repair_access_live(party, now=None):
    """A job is open, or its 24 hours after payment are still running."""
    now = now or timezone.now()
    return repair_job_open(party) or RepairTicket.objects.filter(party=party, portal_until__gt=now).exists()


def repair_only(party, now=None):
    """The portal is here for a repair alone: no rental is running on the account."""
    return party.type != Party.RENTAL or rental_access_ends_at(party, now) is None


def repair_portal_closed(party, now=None):
    """True once a customer with no running rental has repair history and nothing live."""
    now = now or timezone.now()
    if not repair_only(party, now) or repair_access_live(party, now):
        return False
    return RepairTicket.objects.filter(party=party).exists()


def invite_expiry_for(party, now=None):
    """Link expiry for a new invitation; raises ValueError for a Rental customer with no running agreement."""
    now = now or timezone.now()
    if repair_portal_closed(party, now):
        raise ValueError("This customer's repair jobs are all delivered, so a portal link can't be issued.")
    if repair_only(party, now) and repair_job_open(party):
        return now + REPAIR_INVITE_TTL
    if repair_only(party, now) and repair_access_live(party, now):
        return now + NON_RENTAL_INVITE_TTL
    if party.type == Party.RENTAL:
        ends_at = rental_access_ends_at(party, now)
        if ends_at is None:
            raise ValueError(
                "This rental customer has no approved or active rental agreement within its tenure, "
                "so a portal invitation cannot be issued."
            )
        return ends_at
    return now + NON_RENTAL_INVITE_TTL


def invite_closed_code(invite, now=None):
    """None while the link is usable, else a stable error code (invite_revoked / invite_expired)."""
    now = now or timezone.now()
    party = invite.party
    if invite.revoked_at or invite.consumed_at:
        return "invite_revoked"
    if party.portal_access_revoked_at and party.portal_access_revoked_at >= invite.created_at:
        return "invite_revoked"
    if now >= invite.expires_at:
        return "invite_expired"
    if party.type == Party.RENTAL and rental_access_ends_at(party, now) is None and not repair_access_live(party, now):
        return "invite_expired"
    if repair_portal_closed(party, now):
        return "invite_expired"
    return None


def otp_state(invite, now=None):
    """'active', 'expired', 'locked' (too many wrong tries) or 'none' (used, invalidated or never sent)."""
    now = now or timezone.now()
    if not invite.otp_digest:
        return "none"
    if invite.failed_attempts >= MAX_OTP_ATTEMPTS:
        return "locked"
    if invite.otp_expires_at is None or now >= invite.otp_expires_at:
        return "expired"
    return "active"


def resend_wait_seconds(invite, now=None):
    if not invite.otp_issued_at:
        return 0
    now = now or timezone.now()
    ready_at = invite.otp_issued_at + timedelta(seconds=resend_cooldown_seconds())
    return max(0, math.ceil((ready_at - now).total_seconds()))


def mask_email(email):
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain[:1]}***" if local and domain else "the email on file"
