"""Strips what the AI service never needs before CRM data leaves the server."""
import re

DROP = re.compile(r"otp|token|password|secret|signature|hash|url|link|id_documents|kyc|file|photo|provider_", re.I)
MASK = re.compile(r"^(phone|email|gstin|address|alternate_phone|whatsapp|customer_phone|sent_to_phone|recipient)$", re.I)
MAX_CHARS = 14000
LIMIT = MAX_CHARS - 500  # room for the note that says a list was trimmed


def _mask(value):
    text = str(value or "")
    return f"***{text[-4:]}" if len(text) > 4 else ("***" if text else "")


def clean(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if DROP.search(str(key)):
                continue
            out[key] = _mask(item) if MASK.match(str(key)) else clean(item)
        return out
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value
