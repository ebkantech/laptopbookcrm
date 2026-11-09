"""
Customer phone numbers: one check for every place a customer's number is
typed (Parties, the quick "new customer" in an invoice, leads).

Accepted, and stored in one shape so WhatsApp, payment links and search
all see the same number:
  * an Indian mobile -- 10 digits starting 6, 7, 8 or 9, typed bare or with
    +91 / 91 / 0 in front           -> stored as the 10 digits ("9876543210")
  * a foreign number with + and its country code (8-15 digits, e.g.
    +971 50 123 4567)                -> stored as "+971501234567"

Refused with a plain reason: "00" in front (type + instead), letters,
too few/many digits, a 10-digit number not starting 6-9, and dummy
numbers such as 0000000000 or 9999999999.
"""
import re

from rest_framework import serializers

_ALLOWED = re.compile(r"^\+?[\d\s\-().]+$")


def clean_customer_phone(value):
    raw = (value or "").strip()
    if not raw:
        raise serializers.ValidationError("Enter the customer's mobile number.")
    if not _ALLOWED.match(raw):
        raise serializers.ValidationError("A phone number can only have digits (and + at the start).")
    international = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)

    if digits.startswith("00"):
        raise serializers.ValidationError(
            "Don't start the number with 00. Type the 10-digit mobile number, or + and the country code for a foreign number.")

    if international and not digits.startswith("91"):
        if not 8 <= len(digits) <= 15 or digits[0] == "0":
            raise serializers.ValidationError("Enter a foreign number as + country code and number, e.g. +971 50 123 4567.")
        return f"+{digits}"

    # Indian number: drop +91 / 91 / a leading 0
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        raise serializers.ValidationError(
            f"A mobile number has 10 digits — this one has {len(digits)}. For a foreign number type + and the country code.")
    if digits[0] not in "6789":
        raise serializers.ValidationError("An Indian mobile number starts with 6, 7, 8 or 9.")
    if len(set(digits)) == 1:
        raise serializers.ValidationError("That doesn't look like a real number.")
    return digits
