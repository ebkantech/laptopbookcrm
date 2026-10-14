"""
Encrypted record of every portal verification code that was issued, so
staff holding portal.manage can read each code back in its own CRM
history entry -- including after it was used, expired or replaced.

Displaying a code never makes it valid: authentication only ever checks
PortalInvite.otp_digest (a one-way Django password hash of the CURRENT
code, cleared on use and overwritten on resend). This module is display
only.

Codes are Fernet-encrypted (AES-128-CBC + HMAC-SHA256) with a key that
lives only in the server environment (PORTAL_OTP_ENCRYPTION_KEY), and
each ciphertext is bound to its invite token and issue reference, so a
value copied onto another row will not open. No key configured -> no
ciphertext is stored and staff simply can't see codes.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _cipher():
    from cryptography.fernet import Fernet, MultiFernet

    raw = (getattr(settings, "PORTAL_OTP_ENCRYPTION_KEY", "") or "").strip()
    if not raw:
        return None
    try:
        # comma-separated keys allow rotation: the first encrypts, all decrypt
        return MultiFernet([Fernet(key.strip().encode()) for key in raw.split(",") if key.strip()])
    except (ValueError, TypeError):
        logger.error("PORTAL_OTP_ENCRYPTION_KEY is not a valid Fernet key; staff OTP display is disabled.")
        return None


def is_enabled():
    return _cipher() is not None


def binding_for(issue):
    return f"{issue.invite.token}:{issue.ref}"


def seal(binding, code):
    """Ciphertext of `code` bound to `binding`, or "" when no key is configured."""
    cipher = _cipher()
    if cipher is None:
        return ""
    return cipher.encrypt(f"{binding}|{code}".encode()).decode()


def unseal(ciphertext, binding):
    """The six-digit code, or None if absent, tampered, under a different key, or bound to another issue."""
    from cryptography.fernet import InvalidToken

    cipher = _cipher()
    if cipher is None or not ciphertext:
        return None
    try:
        plain = cipher.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
    bound, _, code = plain.rpartition("|")
    if bound != binding or not (len(code) == 6 and code.isdigit()):
        return None
    return code


def unseal_legacy_invite_copy(ciphertext, token):
    """Migration helper: the pre-0009 per-invite copy ("<token>:<code>")."""
    from cryptography.fernet import InvalidToken

    cipher = _cipher()
    if cipher is None or not ciphertext:
        return None
    try:
        plain = cipher.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
    bound, _, code = plain.partition(":")
    return code if bound == str(token) and len(code) == 6 and code.isdigit() else None
