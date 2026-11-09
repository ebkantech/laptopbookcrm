"""
Reading what Settings -> Business & messages holds.

    business()                      the business's details (blank -> .env BUSINESS_*)
    message(key, **values)          the WhatsApp / SMS text of a customer message
    email(key, **values)            (subject, body) of its email
    rental_terms()                  the rental agreement's conditions

A message someone edited badly can never stop a send: an unknown or broken
{placeholder} falls back to the standard wording.
"""
import re
import string
from dataclasses import dataclass, field

from django.conf import settings

from .registry import BY_KEY, COMMON

STANDARD_FOOTER = "Thank you for your business. This is a computer-generated invoice."
STANDARD_SIGNATORY = "Authorised signatory"
FIELD = re.compile(r"\{([^{}]*)\}")


@dataclass
class Business:
    name: str
    address: str = ""
    phone: str = ""
    email: str = ""
    gstin: str = ""
    website: str = ""
    invoice_footer: str = STANDARD_FOOTER
    signatory_label: str = STANDARD_SIGNATORY
    invoice_notes: str = ""
    rental_terms: list = field(default_factory=list)


def _profile():
    from .models import BusinessProfile

    try:
        return BusinessProfile.objects.filter(pk=1).first()
    except Exception:  # table not created yet (before migrate)
        return None


def business():
    p = _profile()
    get = lambda attr, fallback="": (getattr(p, attr, "") or "").strip() or fallback
    return Business(
        name=get("name", settings.BUSINESS_NAME),
        address=get("address", getattr(settings, "BUSINESS_ADDRESS", "")),
        phone=get("phone", settings.BUSINESS_PHONE),
        email=get("email", settings.BUSINESS_EMAIL),
        gstin=get("gstin", settings.BUSINESS_GSTIN),
        website=get("website"),
        invoice_footer=get("invoice_footer", STANDARD_FOOTER),
        signatory_label=get("signatory_label", STANDARD_SIGNATORY),
        invoice_notes=get("invoice_notes"),
        rental_terms=[line.strip() for line in get("rental_terms").splitlines() if line.strip()],
    )


def fields_in(text):
    return {m.group(1) for m in FIELD.finditer(text or "")}


def problems(key, text, *, required=()):
    """Why this wording can't be used, or [] -- unknown {placeholders}, stray braces, a missing required one."""
    allowed = {**BY_KEY[key]["placeholders"], **COMMON}
    found = []
    try:
        list(string.Formatter().parse(text or ""))
    except ValueError:
        return ["A { or } isn't closed. Use {placeholder} with both braces."]
    unknown = sorted(f for f in fields_in(text) if f not in allowed)
    if unknown:
        found.append(f"Unknown placeholder{'s' if len(unknown) > 1 else ''}: {', '.join('{' + u + '}' for u in unknown)}. "
                     f"You can use: {', '.join('{' + a + '}' for a in allowed)}.")
    missing = [r for r in required if r not in fields_in(text)]
    if missing:
        found.append(f"This message must keep {', '.join('{' + m + '}' for m in missing)}.")
    return found


def _fill(template, values):
    return string.Formatter().vformat(template, (), values)


def _render(key, part, values, fallback):
    from .models import MessageText

    spec = BY_KEY[key]
    standard = spec.get(part) if part != "email_body" else spec.get("email_body", spec["body"])
    edited = None
    try:
        row = MessageText.objects.filter(key=key).first()
        if row is not None:
            edited = getattr(row, part) or None
            if part == "email_body" and not edited and not spec.get("email_body"):
                edited = row.body  # an email that says the same as the WhatsApp text
    except Exception:
        row = None
    biz = business()
    values = {"business": biz.name, "business_phone": biz.phone, **{k: ("" if v is None else v) for k, v in values.items()}}
    for template in (edited, standard):
        if not template:
            continue
        try:
            return _fill(template, values)
        except (KeyError, IndexError, ValueError, AttributeError):
            continue
    return fallback


def message(key, **values):
    """The WhatsApp / SMS wording of a customer message, filled in."""
    return _render(key, "body", values, "")


def email(key, **values):
    """(subject, body) of a customer message's email."""
    return _render(key, "subject", values, ""), _render(key, "email_body", values, "")


def pay_note(link):
    """" Pay here: <link>" (with its leading space), or "" without a link."""
    return f" {message('pay_note', link=link)}" if link else ""


def rental_terms(standard):
    """The agreement's conditions: as edited in Settings, else the standard ones."""
    edited = business().rental_terms
    return edited or standard
