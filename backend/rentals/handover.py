"""
Device handover for rental agreements: working-condition checks, photos
of every side + serial label + accessories, the accessories list, and the
shop's warranty for the tenure. All of it is snapshotted into the
customer's approval (services._snapshot), so it's only editable before
approval, and editing withdraws any pending approval link.
"""
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm

from .models import RentalLine, RentalLinePhoto
from .services import HANDOVER_EDITABLE, get_public_approval, handover_changed

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTOS_PER_DEVICE = 30
MAX_ACCESSORIES = 15


def sniff_image_type(head: bytes):
    """Content type from the file's own bytes -- never trust the client's
    filename or declared type for something we later serve back."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


class PhotoSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = RentalLinePhoto
        fields = ["id", "kind", "kind_label", "caption", "uploaded_at"]


class AccessorySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60, trim_whitespace=True)
    serial = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")


class HandoverSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    serial_number = serializers.CharField(source="asset.serial_number", read_only=True)
    description = serializers.CharField(read_only=True)
    accessories = AccessorySerializer(many=True, required=False)
    photos = PhotoSerializer(many=True, read_only=True)
    issues = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    tenure_months = serializers.IntegerField(source="rental.tenure_months", read_only=True)
    handover_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RentalLine
        fields = [
            "id", "asset_tag", "serial_number", "description", "monthly_fee", "tenure_months",
            "checks", "working_confirmed", "condition_notes", "accessories",
            "warranty_included", "warranty_months", "warranty_terms",
            "photos", "issues", "editable", "handover_by_name", "handover_updated_at",
        ]
        read_only_fields = ["monthly_fee", "handover_updated_at"]

    def get_issues(self, obj):
        return obj.handover_issues()

    def get_editable(self, obj):
        return obj.rental.status in HANDOVER_EDITABLE

    def get_handover_by_name(self, obj):
        return (obj.handover_by.get_full_name() or obj.handover_by.username) if obj.handover_by else None

    def validate_checks(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected {check: true/false}.")
        known = {key for key, _ in RentalLine.CHECKS}
        unknown = set(value) - known
        if unknown:
            raise serializers.ValidationError(f"Unknown checks: {', '.join(sorted(unknown))}.")
        return {key: bool(v) for key, v in value.items()}

    def validate_accessories(self, value):
        if len(value) > MAX_ACCESSORIES:
            raise serializers.ValidationError(f"At most {MAX_ACCESSORIES} accessories.")
        return [dict(a) for a in value]

    def validate(self, attrs):
        months = attrs.get("warranty_months", getattr(self.instance, "warranty_months", None))
        if months is not None and self.instance and months > self.instance.rental.tenure_months:
            raise serializers.ValidationError({"warranty_months": "Warranty can't run longer than the rental tenure."})
        return attrs


def _meta():
    return {
        "checks": [{"key": k, "label": label} for k, label in RentalLine.CHECKS],
        "photo_kinds": [{"key": k, "label": label} for k, label in RentalLinePhoto.KIND_CHOICES],
        "required_photo_kinds": [k for k, _ in RentalLinePhoto.REQUIRED_KINDS],
    }


def _line(pk):
    return get_object_or_404(
        RentalLine.objects.select_related("rental", "asset", "handover_by").prefetch_related("photos"), pk=pk,
    )


def _locked(line):
    if line.rental.status not in HANDOVER_EDITABLE:
        return Response(
            {"detail": "Handover details are locked once the agreement is approved -- they're part of what the customer approved."},
            status=400,
        )
    return None


def _changed(line, user, what):
    line.handover_by = user
    line.handover_updated_at = timezone.now()
    line.save(update_fields=["handover_by", "handover_updated_at"])
    return handover_changed(line.rental, user, what)


class RentalLineHandoverView(APIView):
    """GET / PATCH one device's handover record."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]

    @property
    def required_perm(self):
        return "rentals.view" if self.request.method == "GET" else "rentals.manage"

    def get(self, request, pk):
        return Response({**HandoverSerializer(_line(pk)).data, "meta": _meta()})

    def patch(self, request, pk):
        line = _line(pk)
        locked = _locked(line)
        if locked:
            return locked
        serializer = HandoverSerializer(line, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        revoked = _changed(line, request.user, "details")
        line = _line(pk)
        return Response({**HandoverSerializer(line).data, "meta": _meta(), "approval_link_revoked": revoked})


class RentalLinePhotoUploadView(APIView):
    """POST multipart {kind, caption?, image} -- add a handover photo."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "rentals.manage"
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        line = _line(pk)
        locked = _locked(line)
        if locked:
            return locked
        kind = request.data.get("kind")
        if kind not in dict(RentalLinePhoto.KIND_CHOICES):
            return Response({"detail": "Choose what this photo shows."}, status=400)
        upload = request.FILES.get("image")
        if not upload:
            return Response({"detail": "Attach a photo."}, status=400)
        if upload.size > MAX_PHOTO_BYTES:
            return Response({"detail": "Photos must be 10 MB or smaller."}, status=400)
        if line.photos.count() >= MAX_PHOTOS_PER_DEVICE:
            return Response({"detail": f"At most {MAX_PHOTOS_PER_DEVICE} photos per device."}, status=400)
        content_type = sniff_image_type(upload.read(16))
        upload.seek(0)
        if not content_type:
            return Response({"detail": "Upload a JPEG, PNG or WebP photo."}, status=400)
        photo = RentalLinePhoto.objects.create(
            line=line, kind=kind, caption=(request.data.get("caption") or "").strip()[:120],
            image=upload, content_type=content_type, uploaded_by=request.user,
        )
        revoked = _changed(line, request.user, f"photo added ({photo.get_kind_display()})")
        return Response({**PhotoSerializer(photo).data, "approval_link_revoked": revoked}, status=201)


def _photo_response(photo):
    response = FileResponse(photo.image.open("rb"), content_type=photo.content_type)
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response


class RentalLinePhotoView(APIView):
    """GET the image (staff) / DELETE it (before approval)."""
    permission_classes = [permissions.IsAuthenticated, HasPerm]

    @property
    def required_perm(self):
        return "rentals.view" if self.request.method == "GET" else "rentals.manage"

    def get(self, request, pk):
        return _photo_response(get_object_or_404(RentalLinePhoto, pk=pk))

    def delete(self, request, pk):
        photo = get_object_or_404(RentalLinePhoto.objects.select_related("line__rental"), pk=pk)
        line = photo.line
        locked = _locked(line)
        if locked:
            return locked
        label = photo.get_kind_display()
        photo.image.delete(save=False)
        photo.delete()
        revoked = _changed(line, request.user, f"photo removed ({label})")
        return Response({"approval_link_revoked": revoked})


class RentalApprovalPhotoView(APIView):
    """A handover photo seen through the customer's approval link -- only
    photos that are part of that approval's snapshot."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, token, photo_id):
        approval = get_public_approval(token)
        ids = {p["id"] for item in approval.snapshot.get("items", []) for p in item.get("photos", [])}
        if photo_id not in ids:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return _photo_response(get_object_or_404(RentalLinePhoto, pk=photo_id, line__rental=approval.rental))
