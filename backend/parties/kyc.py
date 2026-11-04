"""
Customer ID records (PartyIdDocument): free format checks, Aadhaar masking,
consent, and staff verification.

What the checks can and can't do: they catch typing mistakes (wrong length,
wrong pattern, a bad Aadhaar check digit). They can't tell a real card from
a fake one -- that needs a staff member looking at the original (Verify), or
a paid verification service added later.
"""
import os
import re

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import PartyIdDocument

MAX_FILE_BYTES = 8 * 1024 * 1024
ALLOWED = {"image/jpeg": (".jpg", ".jpeg"), "image/png": (".png",), "application/pdf": (".pdf",)}

# Verhoeff tables (the check digit printed as the last of Aadhaar's 12 digits)
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(digits):
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


PAN_HOLDER = {"P": "an individual", "C": "a company", "H": "a HUF", "F": "a firm / LLP", "A": "an association of persons",
              "T": "a trust", "B": "a body of individuals", "L": "a local authority", "J": "an artificial juridical person",
              "G": "a government body"}


def check_number(id_type, raw):
    """Returns (number to store, check note). Raises ValidationError on a number that can't be right."""
    value = re.sub(r"[\s\-]", "", (raw or "")).upper()
    if not value:
        raise ValidationError({"number": "Enter the ID number."})
    if id_type == PartyIdDocument.AADHAAR:
        if not re.fullmatch(r"[2-9]\d{11}", value):
            raise ValidationError({"number": "An Aadhaar number is 12 digits and doesn't start with 0 or 1."})
        if not verhoeff_ok(value):
            raise ValidationError({"number": "This isn't a valid Aadhaar number -- check the digits (the last digit doesn't match)."})
        return f"XXXX XXXX {value[-4:]}", "Valid Aadhaar number format; stored masked (last 4 digits only)"
    if id_type == PartyIdDocument.PAN:
        if not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", value):
            raise ValidationError({"number": "A PAN is 10 characters: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)."})
        holder = PAN_HOLDER.get(value[3])
        if not holder:
            raise ValidationError({"number": f"The 4th character of a PAN ({value[3]}) doesn't match any PAN holder type."})
        return value, f"Valid PAN format -- issued to {holder}"
    if id_type == PartyIdDocument.PASSPORT:
        if not re.fullmatch(r"[A-Z]\d{7}", value):
            raise ValidationError({"number": "An Indian passport number is 1 letter and 7 digits (e.g. K1234567)."})
        return value, "Valid passport number format"
    if id_type == PartyIdDocument.VOTER_ID:
        if not re.fullmatch(r"[A-Z]{3}\d{7}", value):
            raise ValidationError({"number": "A Voter ID (EPIC) number is 3 letters and 7 digits (e.g. ABC1234567)."})
        return value, "Valid Voter ID format"
    if id_type == PartyIdDocument.DRIVING_LICENCE:
        if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{9,13}", value):
            raise ValidationError({"number": "A driving licence number starts with the state code and RTO number (e.g. DL0420110012345)."})
        return value, "Valid driving licence format"
    if not re.fullmatch(r"[A-Z0-9/]{4,40}", value):
        raise ValidationError({"number": "Use letters and digits only."})
    return value, "Recorded (no format check for this ID type)"


def check_file(upload):
    name = os.path.basename((upload.name or "").replace("\\", "/"))[:150] or "id"
    ext = os.path.splitext(name)[1].lower()
    if upload.size == 0 or upload.size > MAX_FILE_BYTES:
        raise ValidationError({"file": f"The file must be under {MAX_FILE_BYTES // (1024 * 1024)} MB."})
    head = upload.read(8)
    upload.seek(0)
    kind = ("image/jpeg" if head.startswith(b"\xff\xd8\xff") else "image/png" if head.startswith(b"\x89PNG\r\n\x1a\n")
            else "application/pdf" if head.startswith(b"%PDF-") else None)
    if kind is None or ext not in ALLOWED[kind]:
        raise ValidationError({"file": "Upload a JPG, PNG or PDF copy."})
    return kind, name


def _yes(value):
    return value is True or str(value).strip().lower() in ("true", "1", "on", "yes")


def can_record(user):
    return user.has_perm_code("parties.manage") or user.has_perm_code("rentals.manage")


def record(party, user, id_type, number, consent, name_on_id="", upload=None, masked_copy=False):
    if not can_record(user):
        raise PermissionDenied("You do not have permission to record customer IDs.")
    if id_type not in dict(PartyIdDocument.TYPE_CHOICES):
        raise ValidationError({"id_type": "Choose the ID type."})
    if not _yes(consent):
        raise ValidationError({"consent": "The customer's consent is required to record their ID."})
    stored, note = check_number(id_type, number)
    if upload and id_type == PartyIdDocument.AADHAAR and not _yes(masked_copy):
        raise ValidationError({"file": "Only a masked Aadhaar copy (first 8 digits hidden) may be kept. Confirm the copy is masked."})
    doc = PartyIdDocument(party=party, id_type=id_type, number=stored, name_on_id=(name_on_id or "").strip()[:120],
                          status=PartyIdDocument.FORMAT_OK, check_note=note, consent_at=timezone.now(), consent_by=user)
    if upload:
        doc.content_type, doc.original_name = check_file(upload)
        doc.file = upload
    doc.save()
    duplicate = None
    if id_type != PartyIdDocument.AADHAAR:
        other = PartyIdDocument.objects.filter(id_type=id_type, number=stored).exclude(party=party).select_related("party").first()
        if other:
            duplicate = f"The same {doc.get_id_type_display()} is also on file for {other.party.name}."
    return doc, duplicate


def verify(doc, user, outcome, note=""):
    if not can_record(user):
        raise PermissionDenied("You do not have permission to verify customer IDs.")
    note = (note or "").strip()
    if outcome not in ("verified", "failed"):
        raise ValidationError({"outcome": "Choose verified or failed."})
    if outcome == "failed" and not note:
        raise ValidationError({"note": "Say what was wrong with the ID."})
    doc.status = PartyIdDocument.VERIFIED if outcome == "verified" else PartyIdDocument.FAILED
    doc.verified_by, doc.verified_at = user, timezone.now()
    doc.verify_method = "Original seen by staff"
    doc.verify_note = note[:200]
    doc.save(update_fields=["status", "verified_by", "verified_at", "verify_method", "verify_note"])
    return doc


def kyc_status(party):
    """'verified' (an ID checked against the original), 'unverified' (IDs recorded, none checked) or 'none'."""
    docs = list(party.id_documents.all())
    if any(d.status == PartyIdDocument.VERIFIED for d in docs):
        return "verified"
    return "unverified" if docs else "none"
