"""
Settings -> Business & messages.

  GET    /api/branding/                         business details + every customer message
  PATCH  /api/branding/business/                save business details / document wording
  POST   /api/branding/messages/<key>/          save a message's wording
  DELETE /api/branding/messages/<key>/          back to the standard wording
  POST   /api/branding/messages/<key>/preview/  the wording filled with sample values (not saved)

Everyone signed in as staff may read; only the Owner / Super Admin or an
Admin may change anything.
"""
import string

from django.http import Http404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import activity
from accounts.staff import is_staff_admin

from . import texts
from .models import BusinessProfile, MessageText
from .registry import BY_KEY, COMMON, GROUPS, MESSAGES


class CanEditBranding(permissions.BasePermission):
    message = "Only the Owner or an Admin can change business details and customer messages."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or hasattr(user, "customer_profile"):
            return False
        return request.method in permissions.SAFE_METHODS or can_edit(user)


def can_edit(user):
    return bool(user and user.is_authenticated and (user.is_superuser or is_staff_admin(user)))


PROFILE_FIELDS = ["name", "address", "phone", "email", "gstin", "website", "invoice_footer", "signatory_label",
                  "invoice_notes", "rental_terms"]


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessProfile
        fields = PROFILE_FIELDS

    def validate_gstin(self, value):
        value = (value or "").strip().upper()
        if value and len(value) != 15:
            raise serializers.ValidationError("A GSTIN has 15 characters.")
        return value

    def validate_rental_terms(self, value):
        lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
        if len(lines) > 40:
            raise serializers.ValidationError("Keep it to 40 conditions or fewer.")
        return "\n".join(lines)


def _samples(key):
    return {name: sample for name, (_desc, sample) in {**BY_KEY[key]["placeholders"], **COMMON}.items()}


def _fill(template, values):
    try:
        return string.Formatter().vformat(template or "", (), values)
    except (KeyError, IndexError, ValueError):
        return template or ""


def _message_row(spec, row):
    def current(part, standard):
        if row is None:
            return standard
        value = getattr(row, part)
        return value if value else standard

    standard_email = spec.get("email_body", "")
    return {
        "key": spec["key"], "group": spec["group"], "label": spec["label"], "when": spec["when"], "channels": spec["channels"],
        "has_subject": "subject" in spec, "has_email_body": "email_body" in spec,
        "subject": current("subject", spec.get("subject", "")), "body": current("body", spec["body"]),
        "email_body": current("email_body", standard_email),
        "standard": {"subject": spec.get("subject", ""), "body": spec["body"], "email_body": standard_email},
        "edited": row is not None, "updated_at": row.updated_at if row else None,
        "updated_by": (row.updated_by.get_full_name() or row.updated_by.username) if row and row.updated_by else "",
        "placeholders": [{"name": n, "description": d, "sample": s}
                         for n, (d, s) in {**spec["placeholders"], **COMMON}.items()],
        "required": spec.get("required", []),
    }


def _payload(request):
    profile = BusinessProfile.objects.filter(pk=1).first()
    biz = texts.business()
    rows = {r.key: r for r in MessageText.objects.select_related("updated_by")}
    from rentals.documents import terms as standard_terms

    return {
        "can_edit": can_edit(request.user),
        "business": {f: getattr(profile, f, "") if profile else "" for f in PROFILE_FIELDS},
        # what's printed now (blank fields fall back to .env / the standard wording)
        "effective": {"name": biz.name, "address": biz.address, "phone": biz.phone, "email": biz.email, "gstin": biz.gstin,
                      "invoice_footer": biz.invoice_footer, "signatory_label": biz.signatory_label},
        "standard": {"invoice_footer": texts.STANDARD_FOOTER, "signatory_label": texts.STANDARD_SIGNATORY,
                     "rental_terms": "\n".join(standard_terms("{business}"))},
        "groups": GROUPS,
        "messages": [_message_row(spec, rows.get(spec["key"])) for spec in MESSAGES],
    }


class BrandingView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditBranding]

    def get(self, request):
        return Response(_payload(request))


class BusinessView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditBranding]

    def patch(self, request):
        profile, _ = BusinessProfile.objects.get_or_create(pk=1)
        data = BusinessSerializer(profile, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        data.save(updated_by=request.user)
        activity.note(profile, "business-edited", f"Business details edited: {', '.join(sorted(request.data.keys()))}")
        return Response(_payload(request))


class MessageSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    body = serializers.CharField(max_length=4000, trim_whitespace=False)
    email_body = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="", trim_whitespace=False)

    def validate(self, attrs):
        key = self.context["key"]
        spec = BY_KEY[key]
        required = spec.get("required", [])
        errors = {}
        if not attrs["body"].strip():
            errors["body"] = ["The message can't be empty."]
        for part in ("subject", "body", "email_body"):
            text = attrs.get(part) or ""
            if not text:
                continue
            found = texts.problems(key, text, required=required if part in ("body", "email_body") and text else ())
            if found:
                errors[part] = found
        if errors:
            raise serializers.ValidationError(errors)
        if "subject" not in spec:
            attrs["subject"] = ""
        if "email_body" not in spec:
            attrs["email_body"] = ""
        return attrs


class MessageView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditBranding]

    def _spec(self, key):
        if key not in BY_KEY:
            raise Http404("No such message.")
        return BY_KEY[key]

    def post(self, request, key):
        spec = self._spec(key)
        data = MessageSerializer(data=request.data, context={"key": key})
        data.is_valid(raise_exception=True)
        row, _ = MessageText.objects.update_or_create(key=key, defaults={**data.validated_data, "updated_by": request.user})
        activity.note(row, "message-edited", f"Customer message “{spec['label']}” edited")
        return Response(_message_row(spec, row))

    def delete(self, request, key):
        spec = self._spec(key)
        MessageText.objects.filter(key=key).delete()
        return Response(_message_row(spec, None))


class PreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanEditBranding]

    def post(self, request, key):
        if key not in BY_KEY:
            raise Http404("No such message.")
        spec = BY_KEY[key]
        values = _samples(key)
        biz = texts.business()
        values.update(business=biz.name, business_phone=biz.phone or values["business_phone"])
        out = {}
        for part in ("subject", "body", "email_body"):
            text = request.data.get(part) or ""
            out[part] = _fill(text, values) if text else ""
            out[f"{part}_problems"] = texts.problems(key, text, required=spec.get("required", []) if part != "subject" else ()) if text else []
        return Response(out)
