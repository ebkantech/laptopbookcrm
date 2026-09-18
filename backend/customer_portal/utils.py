import hashlib
import re

from django.conf import settings
from rest_framework.exceptions import ValidationError


def normalize_phone(value):
    raw = (value or "").strip()
    digits = re.sub(r"\D", "", raw)
    country_code = str(getattr(settings, "CUSTOMER_PHONE_DEFAULT_COUNTRY_CODE", "91")).lstrip("+")
    if len(digits) == 10:
        digits = f"{country_code}{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        digits = f"{country_code}{digits[1:]}"
    if not 8 <= len(digits) <= 15:
        raise ValidationError({"phone": "Enter a valid registered phone number."})
    return f"+{digits}"


def mask_phone(value):
    value = value or ""
    return f"{'*' * max(0, len(value) - 4)}{value[-4:]}"


def token_hash(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def identifier_hash(identifier):
    return hashlib.sha256((identifier or "").strip().casefold().encode("utf-8")).hexdigest()


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",", 1)[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None
