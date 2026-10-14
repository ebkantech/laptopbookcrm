from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from crmbook_backend.notify import send_email, send_whatsapp, whatsapp_template
from parties.models import Message, Party

from . import access, otp_vault
from .models import PortalInvite, PortalOtpAccessLog, PortalOtpIssue, _generate_otp


class PortalFlowError(Exception):
    """A customer-facing refusal with a stable machine-readable code."""

    def __init__(self, code, detail, status, **extra):
        super().__init__(detail)
        self.code, self.detail, self.status, self.extra = code, detail, status, extra

    def as_data(self):
        return {"detail": self.detail, "code": self.code, **self.extra}


CLOSED_MESSAGES = {
    "invite_expired": "This link has expired. Ask a staff member to send a new one.",
    "invite_revoked": "This link is no longer active. Ask a staff member to send a new one.",
}


def _local(dt):
    return timezone.localtime(dt).strftime("%d %b %Y, %H:%M %Z")


def _email_body(party, code, invite, *, resent=False):
    business = settings.BUSINESS_NAME
    minutes = int(access.OTP_TTL.total_seconds() // 60)
    intro = "Your new one-time verification code" if resent else "Your one-time verification code"
    return (
        f"Hi {party.name},\n\n"
        f"{intro} is {code}. This code expires in {minutes} minutes and can only be used once.\n\n"
        f"Your portal link stays valid until {_local(invite.expires_at)}. If the code expires, "
        "open the same link and request a new code.\n\n"
        f"- {business}"
    )


def invite_whatsapp_body(invite, link):
    minutes = int(access.OTP_TTL.total_seconds() // 60)
    return (
        f"Access your {settings.BUSINESS_NAME} portal here: {link}\n"
        f"This link stays valid until {_local(invite.expires_at)}. "
        f"Each verification code we email you expires {minutes} minutes after it is sent; "
        "you can request a new code from the link."
    )


def send_invite_whatsapp(party, invite, link):
    """
    WhatsApp half of a portal invite, shared by both staff endpoints.
    Uses the approved template WHATSAPP_TEMPLATE_PORTAL_INVITE when
    configured (body {{1}} customer name, {{2}} portal link, {{3}} link
    expiry), else the free-text body. Returns a summary safe to show
    staff: {"status", "reason", "provider_id"}. A number already flagged
    as not on WhatsApp is skipped -- the emailed code covers that customer.
    """
    from .models import WhatsAppDeliveryLog

    if party.whatsapp_verified is False:
        return {"status": "skipped", "reason": "this number was flagged as not on WhatsApp", "provider_id": None}
    template = whatsapp_template("portal_invite", [party.name, link, _local(invite.expires_at)])
    result = send_whatsapp(party.phone, invite_whatsapp_body(invite, link), template=template)
    # A provider_id means the provider accepted the message and may later
    # post a delivery-status webhook against it.
    if result.get("provider_id"):
        WhatsAppDeliveryLog.objects.create(
            party=party, provider_message_id=result["provider_id"], status=WhatsAppDeliveryLog.SENT,
        )
    return {"status": result.get("status"), "reason": result.get("reason"), "provider_id": result.get("provider_id")}


OTP_MASK = "******"


def _put_new_otp(invite, now):
    code = _generate_otp()
    invite.set_otp(code)
    invite.otp_issued_at = now
    invite.otp_expires_at = now + access.OTP_TTL
    invite.failed_attempts = 0
    return code


def _delivery_label(status):
    if status != "sent":
        return "failed"
    # The console backend only prints the email to the server console;
    # don't represent that as customer delivery.
    return "console" if "console" in settings.EMAIL_BACKEND.lower() else "sent"


def _history_title(invite, title, sequence=None):
    return f"{title} · Invitation #{invite.pk}" + (f" · Code {sequence}" if sequence else "")


def _record_email(invite, subject, body, code, *, title, delivery, sequence=None):
    """
    A NEW entry on the customer's CRM email thread for a code email. The
    stored text keeps the code masked; the CRM fills in the digits for
    portal.manage staff from that code's encrypted PortalOtpIssue.
    """
    return Message.objects.create(
        party=invite.party, channel=Message.EMAIL, direction=Message.OUT,
        body=(
            f"{_history_title(invite, title, sequence)}\n"
            f"To: {invite.party.email}\nSubject: {subject}\n"
            f"Sent: {timezone.localtime().strftime('%d %b %Y %H:%M %Z')} · delivery: {delivery}\n\n"
            + body.replace(code, OTP_MASK)
        ),
    )


def _record_issue(invite, code, *, kind, issued_at, message):
    sequence = (invite.otp_issues.aggregate(top=Max("sequence"))["top"] or 0) + 1
    issue = PortalOtpIssue(
        invite=invite, sequence=sequence, kind=kind, issued_at=issued_at,
        expires_at=issued_at + access.OTP_TTL, message=message,
    )
    issue.otp_ciphertext = otp_vault.seal(otp_vault.binding_for(issue), code)
    issue.save()
    return issue


def _open_issues(invite):
    return PortalOtpIssue.objects.filter(invite=invite, used_at__isnull=True, superseded_at__isnull=True, locked_at__isnull=True)


def create_portal_invite(party, issued_by):
    """
    Create an invitation and deliver its first one-time code by email.

    The link expiry depends on the customer type (portal.access). Older
    still-open invitations of the party are revoked as "replaced".

    A new "Portal Invitation Generated" entry goes on the customer's CRM
    email thread (code masked in storage), plus a PortalOtpIssue holding
    the code encrypted for portal.manage staff. With no SMTP provider
    configured the console backend prints the email to the runserver
    terminal only (development).
    """
    recent = PortalInvite.objects.filter(
        party=party, created_at__gte=timezone.now() - timedelta(hours=1),
    ).count()
    if recent >= 3:
        raise ValidationError("The link resend limit was reached. Try again later.")
    if not party.email:
        # the code only ever travels by email, so a link without one could never be used
        raise ValidationError("Add an email address for this customer first: portal verification codes are sent only by email.")
    now = timezone.now()
    try:
        expires_at = access.invite_expiry_for(party, now)
    except ValueError as error:
        raise ValidationError(str(error))
    with transaction.atomic():
        PortalInvite.objects.filter(party=party, revoked_at__isnull=True, consumed_at__isnull=True).update(
            revoked_at=now, revoked_reason=PortalInvite.REPLACED,
        )
        invite = PortalInvite(party=party, issued_by=issued_by, expires_at=expires_at)
        code = _put_new_otp(invite, now)
        invite.save()
        subject = f"Your {settings.BUSINESS_NAME} portal verification code"
        body = _email_body(party, code, invite)
        delivery_status = _delivery_label(send_email(party.email, subject, body)["status"])
        if delivery_status == "failed":
            # rolls back the invite, the replacement of older links and any record
            raise ValidationError("The verification email could not be delivered. Check the email provider configuration and try again.")
        message = _record_email(invite, subject, body, code, title="Portal Invitation Generated", delivery=delivery_status, sequence=1)
        _record_issue(invite, code, kind=PortalOtpIssue.INVITATION, issued_at=now, message=message)
    return invite, delivery_status


def _locked_invite(token):
    invite = (
        PortalInvite.objects.select_for_update(of=("self",)).select_related("party")
        .filter(token=token).first()
    )
    if not invite:
        raise PortalFlowError("invite_invalid", "This link is not valid.", 404)
    closed = access.invite_closed_code(invite)
    if closed:
        raise PortalFlowError(closed, CLOSED_MESSAGES[closed], 410)
    return invite


def resend_otp(token):
    """
    Replace the link's code with a fresh one and email it. Invite expiry
    is never touched.

    Ordering, all under the invite's row lock: the new code is generated
    and emailed FIRST, and only written over the old one once the email
    service accepted it. So at every instant exactly one code is valid --
    the old one until delivery succeeds, the new one after; a failed send
    leaves the old code working and reports failure. Concurrent resends
    and verifies wait on the lock (for up to EMAIL_TIMEOUT while the email
    is submitted), then see the result. Limitation: if the database
    commit itself fails after the email was accepted, the customer holds
    a code that never became valid and must request another.
    """
    with transaction.atomic():
        invite = _locked_invite(token)
        party = invite.party
        if not party.email:
            raise PortalFlowError(
                "no_email_on_file",
                "There is no email address on file to send a code to. Please contact our team.", 409,
            )
        wait = access.resend_wait_seconds(invite)
        if wait:
            raise PortalFlowError(
                "resend_throttled", f"Please wait {wait} seconds before requesting another code.", 429,
                retry_after=wait, resend_available_in=wait,
            )
        now = timezone.now()
        old_digest = invite.otp_digest
        fresh = PortalInvite(expires_at=invite.expires_at)
        code = _put_new_otp(fresh, now)
        subject = f"Your new {settings.BUSINESS_NAME} portal verification code"
        body = _email_body(party, code, invite, resent=True)
        delivery_status = _delivery_label(send_email(party.email, subject, body)["status"])
        failure = None
        if delivery_status == "failed":
            failure = PortalFlowError(
                "email_delivery_failed",
                "We couldn't send a new code right now. Your previous code (if any) still works; please try again shortly.", 503,
            )
        else:
            swapped = PortalInvite.objects.filter(pk=invite.pk, otp_digest=old_digest).update(
                otp_digest=fresh.otp_digest, otp_issued_at=now, otp_expires_at=fresh.otp_expires_at, failed_attempts=0,
            )
            if swapped != 1:  # only reachable where row locks are unavailable
                delivery_status = "superseded"
                failure = PortalFlowError("resend_conflict", "Another request changed this code. Please request a new code.", 409)
        if failure is None:
            # the earlier code stops working now (digest swapped above); its history row is labelled, never erased
            _open_issues(invite).update(superseded_at=now)
            sequence = (invite.otp_issues.aggregate(top=Max("sequence"))["top"] or 0) + 1
            message = _record_email(invite, subject, body, code, title="OTP Resent by Customer", delivery=delivery_status, sequence=sequence)
            _record_issue(invite, code, kind=PortalOtpIssue.RESEND, issued_at=now, message=message)
        else:
            # no code was issued: say so, and keep the new (never-valid) code out of the record entirely
            Message.objects.create(
                party=party, channel=Message.EMAIL, direction=Message.OUT,
                body=(
                    f"{_history_title(invite, 'OTP Resend Failed')}\nTo: {party.email}\n"
                    f"Attempted: {timezone.localtime().strftime('%d %b %Y %H:%M %Z')} · delivery: {delivery_status}\n\n"
                    "No new verification code was issued. The previous code, if still valid, is unchanged."
                ),
            )
        invite.refresh_from_db()
    if failure:
        raise failure
    return invite


def verify_otp(token, otp):
    """
    Check one code against the link. Success clears the code (single-use)
    but leaves the link open. The final clearing is a compare-and-swap on
    otp_digest so two simultaneous requests -- or a verify racing a
    resend -- can never both succeed with the same code, even on
    databases where select_for_update is a no-op.
    """
    with transaction.atomic():
        invite = _locked_invite(token)
        state = access.otp_state(invite)
        if state == "none":
            raise PortalFlowError("otp_invalid", "This code is no longer valid. Request a new code.", 400)
        if state == "locked":
            raise PortalFlowError(
                "otp_attempts_exceeded", "Too many incorrect codes. Request a new code to try again.", 400,
                attempts_remaining=0,
            )
        if state == "expired":
            raise PortalFlowError("otp_expired", "This code has expired. Request a new code.", 400)

        # failures below are raised only after the block commits, so the
        # failed-attempt increment is never rolled back
        failure = None
        digest = invite.otp_digest
        if not invite.check_otp(otp):
            PortalInvite.objects.filter(pk=invite.pk, otp_digest=digest).update(failed_attempts=F("failed_attempts") + 1)
            invite.refresh_from_db(fields=["failed_attempts"])
            remaining = max(0, access.MAX_OTP_ATTEMPTS - invite.failed_attempts)
            if remaining == 0:
                _open_issues(invite).update(locked_at=timezone.now())
                failure = PortalFlowError(
                    "otp_attempts_exceeded", "Too many incorrect codes. Request a new code to try again.", 400,
                    attempts_remaining=0,
                )
            else:
                failure = PortalFlowError(
                    "otp_invalid", "That code doesn't match. Check the email and try again.", 400,
                    attempts_remaining=remaining,
                )
        else:
            claimed = PortalInvite.objects.filter(pk=invite.pk, otp_digest=digest).update(
                otp_digest="", otp_expires_at=None, failed_attempts=0, last_verified_at=timezone.now(),
            )
            if claimed != 1:
                failure = PortalFlowError("otp_invalid", "This code is no longer valid. Request a new code.", 400)
            else:
                _open_issues(invite).update(used_at=timezone.now())
    if failure:
        raise failure
    return invite


def invite_status_data(invite, now=None):
    now = now or timezone.now()
    state = access.otp_state(invite, now)
    if state == "active":
        otp_expires_at = invite.otp_expires_at
        otp_expires_in = max(0, int((otp_expires_at - now).total_seconds()))
    elif state == "expired" and invite.otp_expires_at:
        # an expired code is reported as 0 seconds left, never as active
        otp_expires_at, otp_expires_in = invite.otp_expires_at, 0
    else:
        otp_expires_at, otp_expires_in = None, None
    return {
        "valid": True,
        "status": "active",
        "masked_email": access.mask_email(invite.party.email),
        "expires_at": invite.expires_at,
        "invite_expires_at": invite.expires_at,
        "otp_status": state,
        "otp_expires_at": otp_expires_at,
        "otp_expires_in": otp_expires_in,
        "otp_attempts_remaining": max(0, access.MAX_OTP_ATTEMPTS - invite.failed_attempts) if state in ("active", "locked") else None,
        "resend_available_in": access.resend_wait_seconds(invite, now),
        "server_time": now,
    }


def invite_policy_data(invite):
    """What staff need to word the link correctly (the CRM never hardcodes an expiry)."""
    return {
        "party_type": access.account_type(invite.party),
        "invite_expires_at": invite.expires_at,
        "link_policy": "rental_tenure" if invite.party.type == Party.RENTAL else "24_hours",
        "otp_expires_at": invite.otp_expires_at,
        "otp_ttl_minutes": int(access.OTP_TTL.total_seconds() // 60),
    }


def issue_status(issue, closed_code, now=None):
    """History label for one issued code. Purely descriptive -- validity lives in PortalInvite.otp_digest."""
    now = now or timezone.now()
    if issue.used_at:
        return "used"
    if issue.superseded_at:
        return "superseded"
    if issue.locked_at:
        return "locked"
    if closed_code == "invite_revoked":
        return "revoked"
    if closed_code or now >= issue.expires_at:
        return "expired"
    return "active"


def otp_history(party, now=None):
    """Every code issued to this party, oldest first, with its history entry, status and (decrypted) value."""
    now = now or timezone.now()
    rows = []
    issues = PortalOtpIssue.objects.filter(invite__party=party).select_related("invite__party").order_by("issued_at", "id")
    closed = {}
    for issue in issues:
        if issue.invite_id not in closed:
            closed[issue.invite_id] = access.invite_closed_code(issue.invite, now)
        rows.append({
            "message_id": issue.message_id,
            "invite_id": issue.invite_id,
            "sequence": issue.sequence,
            "kind": issue.kind,
            "label": issue.get_kind_display(),
            "otp": otp_vault.unseal(issue.otp_ciphertext, otp_vault.binding_for(issue)),
            "status": issue_status(issue, closed[issue.invite_id], now),
            "issued_at": issue.issued_at,
            "expires_at": issue.expires_at,
        })
    return rows


def current_staff_otp(party):
    """(issue_row, code) for the party's one ACTIVE code, else (None, None)."""
    active = [row for row in otp_history(party) if row["status"] == "active" and row["otp"]]
    return (active[-1], active[-1]["otp"]) if active else (None, None)


def log_otp_disclosure(request, party, count):
    if count:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        PortalOtpAccessLog.objects.create(
            user=request.user if request.user.is_authenticated else None, party=party, path=request.path[:200],
            codes_disclosed=count,
            ip_address=(forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None,
        )


def revoke_open_invites(party, reason=PortalInvite.ACCESS_REVOKED):
    return PortalInvite.objects.filter(party=party, revoked_at__isnull=True, consumed_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_reason=reason,
    )
