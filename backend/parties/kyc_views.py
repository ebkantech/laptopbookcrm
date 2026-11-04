from urllib.parse import quote

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsStaffAccount
from . import kyc
from .models import Party, PartyIdDocument


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def row(d):
    return {
        "id": d.id, "party": d.party_id, "id_type": d.id_type, "id_type_label": d.get_id_type_display(),
        "number": d.number, "name_on_id": d.name_on_id, "status": d.status, "status_label": d.get_status_display(),
        "check_note": d.check_note, "consent_at": d.consent_at, "consent_by": _name(d.consent_by),
        "verified_by": _name(d.verified_by), "verified_at": d.verified_at, "verify_method": d.verify_method,
        "verify_note": d.verify_note, "has_file": bool(d.file), "file_name": d.original_name, "created_at": d.created_at,
    }


class PartyIdDocumentViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    Customer IDs. GET ?party=<id>; POST (multipart) party, id_type, number,
    consent, name_on_id?, file?, masked_copy?; POST <id>/verify/ {outcome, note};
    GET <id>/file/ streams the copy to staff who can record IDs; DELETE removes it.
    """
    queryset = PartyIdDocument.objects.select_related("party", "consent_by", "verified_by").all()
    permission_classes = [permissions.IsAuthenticated, IsStaffAccount]

    def _need(self, user, code=None):
        ok = kyc.can_record(user) or (code and user.has_perm_code(code))
        if not ok:
            raise PermissionDenied("You do not have permission to see customer IDs.")

    def list(self, request):
        user = request.user
        if not (kyc.can_record(user) or user.has_perm_code("parties.view") or user.has_perm_code("rentals.view")):
            raise PermissionDenied("You do not have permission to see customer IDs.")
        party_id = request.query_params.get("party")
        if not party_id:
            raise ValidationError({"party": "party is required."})
        docs = self.get_queryset().filter(party_id=party_id)
        return Response({"status": kyc.kyc_status(get_object_or_404(Party, pk=party_id)), "documents": [row(d) for d in docs]})

    def create(self, request):
        party = get_object_or_404(Party, pk=request.data.get("party"))
        doc, duplicate = kyc.record(party, request.user, request.data.get("id_type"), request.data.get("number"),
                                    request.data.get("consent"), request.data.get("name_on_id", ""),
                                    request.FILES.get("file"), request.data.get("masked_copy"))
        return Response({**row(doc), "warning": duplicate}, status=201)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        doc = kyc.verify(self.get_object(), request.user, request.data.get("outcome"), request.data.get("note"))
        return Response(row(doc))

    @action(detail=True, methods=["get"])
    def file(self, request, pk=None):
        doc = self.get_object()
        if not kyc.can_record(request.user):
            raise PermissionDenied("You do not have permission to open ID copies.")
        if not doc.file:
            raise ValidationError({"detail": "No copy was uploaded for this ID."})
        response = FileResponse(doc.file.open("rb"), content_type=doc.content_type)
        response["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(doc.original_name or 'id')}"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        return response

    def destroy(self, request, *args, **kwargs):
        if not request.user.has_perm_code("parties.manage"):
            raise PermissionDenied("Only staff who manage parties can delete a customer's ID record.")
        doc = self.get_object()
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        return Response(status=204)
