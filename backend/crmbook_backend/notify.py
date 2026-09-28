"""
Outbound WhatsApp/email sending, behind one function per channel.

Every place in the app that "sends" something to a customer (portal
invites, repair/rental notifications, warranty confirmations, the ad-hoc
message box on the Parties page) calls send_whatsapp()/send_email()
below instead of talking to a provider directly. That's the whole point:
swapping in a real provider later is a config change in ONE file, not a
hunt through every view that creates a Message/Notification row.

Both functions are deliberately fail-soft -- they log and return a
status dict, but never raise. A WhatsApp/email send failing must never
turn into a 500 on an otherwise-successful action (creating a repair
ticket, settling an invoice, etc.). The Message/Notification row in the
database is the durable record of "this was communicated to the
customer"; these functions are the (currently simulated) delivery
attempt on top of that.

See docs/NOTIFICATIONS.md for the full role -> channel mapping.
"""
import logging
import os

logger = logging.getLogger("crmbook.notify")


def send_whatsapp(to: str, body: str) -> dict:
    """
    to: E.164-ish phone number as stored on Party.phone (whatever
        format your data is already in -- Meta's Cloud API wants
        digits only with country code, no '+', so the real provider
        below normalizes it).
    Returns {"status": "sent" | "simulated" | "skipped" | "failed", "provider_id": str | None}.
    """
    if not to:
        print(f"\n[WhatsApp] SKIPPED -- no phone number on file. Body would have been:\n{body}\n{'-' * 79}")
        logger.warning("[WhatsApp] skipped -- no phone number on file")
        return {"status": "skipped", "reason": "party has no phone number on file"}

    provider = os.environ.get("WHATSAPP_PROVIDER", "console")
    try:
        if provider == "meta_cloud":
            return _send_whatsapp_meta_cloud(to, body)
        return _send_whatsapp_console(to, body)
    except Exception:
        logger.exception("WhatsApp send failed (provider=%s) to=%s", provider, to)
        return {"status": "failed", "provider_id": None}


def check_whatsapp_number(phone: str) -> dict:
    """
    Task 3 (Party WhatsApp verification pipeline): "does this number have
    WhatsApp" -- runs once per number (at party create/edit), not per
    message. Same provider-swap shape as send_whatsapp(): today there's
    no WhatsApp Business API provider picked yet (Task 2's open decision
    -- Meta Cloud API vs. a BSP like Gupshup/Twilio/AiSensy), so this
    runs a sandbox check; flipping WHATSAPP_PROVIDER=meta_cloud later
    also flips this to a real contact-check call, in one place.

    Returns {"has_whatsapp": bool | None, "checked": bool, "reason": str | None}.
    has_whatsapp is None only when the check itself couldn't run at all
    (e.g. no phone number on file) -- that's different from a real "no".
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        return {"has_whatsapp": None, "checked": False, "reason": "no phone number on file"}

    provider = os.environ.get("WHATSAPP_PROVIDER", "console")
    try:
        if provider == "meta_cloud":
            return _check_whatsapp_meta_cloud(digits)
        return _check_whatsapp_sandbox(digits)
    except Exception:
        logger.exception("WhatsApp number check failed (provider=%s) phone=%s", provider, phone)
        return {"has_whatsapp": None, "checked": False, "reason": "check failed"}


def _check_whatsapp_sandbox(digits: str) -> dict:
    """
    No live provider wired yet -- this is a plausibility check, not a
    real "is this number on WhatsApp" answer: valid-looking Indian
    mobile numbers (10 digits, or 12 with a 91 country code, starting
    2-9) pass; anything else (too short, a landline-shaped number, a
    junk value) is flagged so staff can confirm it before relying on
    WhatsApp delivery. Swap this out for a real provider call (Task 2)
    without touching any caller -- check_whatsapp_number()'s return
    shape stays the same.
    """
    local = digits[2:] if len(digits) == 12 and digits.startswith("91") else digits
    plausible = len(local) == 10 and local[0] in "6789"
    logger.info("[WhatsApp check:sandbox -- simulated, no real provider] phone=%s plausible=%s", digits, plausible)
    return {"has_whatsapp": plausible, "checked": True, "reason": None if plausible else "number doesn't look like a valid mobile number"}


def _check_whatsapp_meta_cloud(digits: str) -> dict:
    """
    Real contact-check via Meta's WhatsApp Cloud API `/contacts` endpoint.
    Needs the same WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN env
    vars as _send_whatsapp_meta_cloud -- not usable until Task 2's
    provider decision lands and those are set.
    """
    import requests

    phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    access_token = os.environ["WHATSAPP_ACCESS_TOKEN"]

    resp = requests.post(
        f"https://graph.facebook.com/v20.0/{phone_number_id}/contacts",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"blocking": "wait", "contacts": [digits]},
        timeout=10,
    )
    if resp.ok:
        contacts = resp.json().get("contacts") or []
        status = (contacts[0].get("status") if contacts else None)
        return {"has_whatsapp": status == "valid", "checked": True, "reason": status}
    logger.error("[WhatsApp check:meta_cloud] phone=%s status=%s body=%s", digits, resp.status_code, resp.text)
    return {"has_whatsapp": None, "checked": False, "reason": f"provider error {resp.status_code}"}


def send_email(to: str, subject: str, body: str) -> dict:
    """Returns {"status": "sent" | "skipped" | "failed"}."""
    if not to:
        logger.warning("[Email] skipped -- no email on file (subject would have been: %r)", subject)
        return {"status": "skipped", "reason": "party has no email on file"}

    from django.conf import settings
    from django.core.mail import send_mail

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@vantagecomputers.example"),
            recipient_list=[to],
            fail_silently=False,
        )
        # With EMAIL_BACKEND left at Django's console backend (the
        # default here -- see settings.py), "sent" means "printed to
        # the runserver terminal", which is exactly the point for
        # testing: nothing external is contacted yet.
        return {"status": "sent"}
    except Exception:
        logger.exception("Email send failed to=%s subject=%s", to, subject)
        return {"status": "failed"}


def notify_staff(event_key: str, subject: str, body: str) -> None:
    """
    Task 2: internal staff alerts, role-gated via
    accounts.models.NotificationRule -- separate from the
    customer-facing send_whatsapp()/send_email() above (those tell a
    customer about their own repair/rental/order; this tells STAFF
    that something happened their role cares about, e.g. a new repair
    ticket or a low customer rating). Which roles get which channel
    for which event is configured on the Settings > Staff alerts
    screen, not hardcoded here.

    Also writes a StaffNotification row per recipient when their role's
    rule has via_inapp on -- that's the in-app inbox behind the header's
    notification bell (PageHeader.jsx > NotificationBell), read through
    GET /my-notifications/. In-app is independent of email/WhatsApp: a
    role can be in-app-only with both those off.

    Deliberately returns nothing and never raises -- a call site fires
    this as a side effect of an already-successful action (creating a
    ticket, saving feedback), and a broken/misconfigured alert must
    never turn that into a 500. Each recipient's send is also wrapped
    individually so one bad email/phone on file doesn't stop the rest
    of the role from being notified.
    """
    from accounts.models import NotificationRule, StaffNotification, User

    try:
        rules = list(NotificationRule.objects.filter(event_key=event_key).select_related("role"))
    except Exception:
        logger.exception("notify_staff: couldn't load rules for event=%s", event_key)
        return

    for rule in rules:
        if not rule.via_email and not rule.via_whatsapp and not rule.via_inapp:
            continue
        for user in User.objects.filter(role=rule.role):
            try:
                if rule.via_email and user.email:
                    send_email(user.email, subject, body)
                if rule.via_whatsapp and user.phone:
                    send_whatsapp(user.phone, body)
                if rule.via_inapp:
                    StaffNotification.objects.create(user=user, event_key=event_key, subject=subject, body=body)
            except Exception:
                logger.exception("notify_staff: send failed event=%s user=%s", event_key, user.pk)


def _send_whatsapp_console(to: str, body: str) -> dict:
    # print(), not just logger.info() -- guaranteed to reach the
    # runserver terminal regardless of any logging configuration
    # subtlety, the same way Django's own console email backend works.
    print(f"\n[WhatsApp:console -- simulated, no real send] to={to}\n{body}\n{'-' * 79}")
    logger.info("[WhatsApp:console -- simulated, no real send] to=%s", to)
    return {"status": "simulated", "provider_id": None}


def _send_whatsapp_meta_cloud(to: str, body: str) -> dict:
    """
    Real send via Meta's WhatsApp Cloud API. Not usable yet -- needs a
    Meta Business Manager account with the WhatsApp product added, plus:
      WHATSAPP_PROVIDER=meta_cloud          (env var -- flips the switch)
      WHATSAPP_PHONE_NUMBER_ID=<...>        (from the Meta developer console)
      WHATSAPP_ACCESS_TOKEN=<...>           (a permanent System User token,
                                              not the 24-hour temporary one)
    Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
    Note: outside a 24-hour customer-initiated window, Meta requires a
    pre-approved message *template* rather than free-form text like
    this -- that's a real product decision (which templates, what
    approval lag) to make once this is actually turned on, not before.
    """
    import requests

    phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    access_token = os.environ["WHATSAPP_ACCESS_TOKEN"]
    to_digits = "".join(c for c in to if c.isdigit())

    resp = requests.post(
        f"https://graph.facebook.com/v20.0/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "messaging_product": "whatsapp",
            "to": to_digits,
            "type": "text",
            "text": {"body": body},
        },
        timeout=10,
    )
    if resp.ok:
        message_id = (resp.json().get("messages") or [{}])[0].get("id")
        return {"status": "sent", "provider_id": message_id}
    logger.error("[WhatsApp:meta_cloud] to=%s status=%s body=%s", to, resp.status_code, resp.text)
    return {"status": "failed", "provider_id": None}
