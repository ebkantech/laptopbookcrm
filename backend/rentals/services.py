import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .models import Rental, RentalApproval, RentalAsset, RentalEvent


APPROVAL_LINK_TTL = timedelta(hours=24)


class RentalApprovalLinkGone(APIException):
    status_code = 410
    default_detail = "This approval link is invalid or has expired."
    default_code = "rental_approval_link_gone"


class RentalApprovalConflict(APIException):
    status_code = 409
    default_detail = "A final decision has already been recorded for this rental agreement."
    default_code = "rental_approval_conflict"


def approval_token_hash(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def build_approval_url(raw_token):
    return f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/rental-approval/{raw_token}"


def _record_event(rental, event_type, actor=None, approval=None, metadata=None):
    return RentalEvent.objects.create(
        rental=rental,
        event_type=event_type,
        actor=actor,
        approval=approval,
        metadata=metadata or {},
    )


def _expire_pending_links(rental, now=None):
    now = now or timezone.now()
    return rental.approvals.filter(
        status=RentalApproval.PENDING, expires_at__lte=now
    ).update(status=RentalApproval.EXPIRED)


def _snapshot(rental):
    lines = list(rental.lines.select_related("asset").order_by("id"))
    if not lines:
        raise ValidationError({"lines": "Add at least one physical rental asset before requesting approval."})
    if any(not line.asset.asset_tag or not line.asset.serial_number for line in lines):
        raise ValidationError({"lines": "Every rental asset requires both an asset tag and serial number."})
    return {
        "agreement_code": rental.agreement_code or f"RENTAL-{rental.pk}",
        "customer": {
            "name": rental.party.name,
            "phone": rental.party.phone,
            "classification": rental.party.customer_classification,
        },
        "start": rental.start.isoformat(),
        "tenure_months": rental.tenure_months,
        "currency": "INR",
        "terms": rental.terms,
        "rental_type": "bulk" if len(lines) >= 2 else "single",
        "items": [
            {
                "asset_tag": line.asset.asset_tag,
                "serial_number": line.asset.serial_number,
                "brand": line.asset.brand,
                "model_name": line.asset.model_name,
                "monthly_fee": line.monthly_fee,
            }
            for line in lines
        ],
        "total_monthly_fee": sum(line.monthly_fee for line in lines),
    }


@transaction.atomic
def issue_approval_link(rental, user):
    rental = Rental.objects.select_for_update().select_related("party").get(pk=rental.pk)
    if rental.status in (Rental.REJECTED, Rental.CANCELLED, Rental.CLOSED):
        raise ValidationError({"detail": "Approval links cannot be created for a rejected, cancelled, or closed agreement."})
    if rental.approvals.filter(status=RentalApproval.APPROVED).exists():
        raise ValidationError({"detail": "This agreement already has a final approval."})
    now = timezone.now()
    _expire_pending_links(rental, now)
    rental.approvals.filter(status=RentalApproval.PENDING).update(status=RentalApproval.REVOKED)
    snapshot = _snapshot(rental)
    version = (rental.approvals.aggregate(value=Max("version"))["value"] or 0) + 1
    raw_token = secrets.token_urlsafe(32)
    approval = RentalApproval.objects.create(
        rental=rental,
        version=version,
        snapshot=snapshot,
        token_hash=approval_token_hash(raw_token),
        requested_by=user,
        expires_at=now + APPROVAL_LINK_TTL,
    )
    rental.status = Rental.PENDING_APPROVAL
    rental.save(update_fields=["status"])
    _record_event(rental, RentalEvent.APPROVAL_LINK_CREATED, actor=user, approval=approval, metadata={"version": version, "expires_at": approval.expires_at.isoformat()})
    return approval, build_approval_url(raw_token)


def get_public_approval(raw_token, for_update=False):
    if not raw_token or len(raw_token) > 200:
        raise NotFound("This approval link is invalid or has expired.")
    queryset = RentalApproval.objects.select_related("rental")
    if for_update:
        queryset = queryset.select_for_update()
    try:
        approval = queryset.get(token_hash=approval_token_hash(raw_token))
    except RentalApproval.DoesNotExist as exc:
        raise NotFound("This approval link is invalid or has expired.") from exc
    now = timezone.now()
    if approval.expires_at and now >= approval.expires_at:
        if approval.status == RentalApproval.PENDING:
            RentalApproval.objects.filter(pk=approval.pk, status=RentalApproval.PENDING).update(status=RentalApproval.EXPIRED)
        raise RentalApprovalLinkGone()
    if approval.status in (RentalApproval.EXPIRED, RentalApproval.REVOKED):
        raise RentalApprovalLinkGone()
    return approval


def customer_decide(raw_token, decision, consent=False, reason=""):
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose either approve or reject."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed the rental agreement and charges."})
    try:
        with transaction.atomic():
            approval = get_public_approval(raw_token, for_update=True)
            desired_status = RentalApproval.APPROVED if decision == "approve" else RentalApproval.REJECTED
            if approval.status in (RentalApproval.APPROVED, RentalApproval.REJECTED):
                if approval.status == desired_status:
                    return approval
                raise RentalApprovalConflict("A different final decision has already been recorded.")
            if approval.status != RentalApproval.PENDING:
                raise RentalApprovalLinkGone()
            if RentalApproval.objects.filter(rental=approval.rental, status=RentalApproval.APPROVED).exclude(pk=approval.pk).exists():
                raise RentalApprovalConflict()
            updated = RentalApproval.objects.filter(pk=approval.pk, status=RentalApproval.PENDING).update(
                status=desired_status,
                source=RentalApproval.CUSTOMER,
                reason=(reason or "").strip(),
                decided_at=timezone.now(),
            )
            if updated != 1:
                raise RentalApprovalConflict()
            approval.refresh_from_db()
            approval.rental.status = Rental.APPROVED if desired_status == RentalApproval.APPROVED else Rental.REJECTED
            approval.rental.save(update_fields=["status"])
            asset_status = RentalAsset.RENTED if desired_status == RentalApproval.APPROVED else RentalAsset.AVAILABLE
            RentalAsset.objects.filter(rental_lines__rental=approval.rental).update(status=asset_status)
            _record_event(approval.rental, RentalEvent.APPROVAL_DECIDED, approval=approval, metadata={"decision": desired_status, "source": RentalApproval.CUSTOMER})
            return approval
    except IntegrityError as exc:
        raise RentalApprovalConflict() from exc


def approve_on_behalf(rental, user, reason):
    if not user.has_perm_code("rentals.approve"):
        raise PermissionDenied("You do not have permission to approve rental agreements.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required for Admin or Super Admin approval."})
    try:
        with transaction.atomic():
            rental = Rental.objects.select_for_update().get(pk=rental.pk)
            if rental.status in (Rental.CANCELLED, Rental.CLOSED):
                raise ValidationError({"detail": "A cancelled or closed agreement cannot be approved."})
            if rental.approvals.filter(status=RentalApproval.APPROVED).exists():
                raise RentalApprovalConflict()
            now = timezone.now()
            _expire_pending_links(rental, now)
            rental.approvals.filter(status=RentalApproval.PENDING).update(status=RentalApproval.REVOKED)
            snapshot = _snapshot(rental)
            version = (rental.approvals.aggregate(value=Max("version"))["value"] or 0) + 1
            source = RentalApproval.SUPERADMIN if user.is_superuser else RentalApproval.ADMIN
            approval = RentalApproval.objects.create(rental=rental, version=version, snapshot=snapshot, status=RentalApproval.APPROVED, source=source, requested_by=user, decided_by=user, reason=reason, decided_at=now)
            rental.status = Rental.APPROVED
            rental.save(update_fields=["status"])
            RentalAsset.objects.filter(rental_lines__rental=rental).update(status=RentalAsset.RENTED)
            _record_event(rental, RentalEvent.APPROVAL_DECIDED, actor=user, approval=approval, metadata={"decision": "approved", "source": source, "reason": reason})
            return approval
    except IntegrityError as exc:
        raise RentalApprovalConflict() from exc


@transaction.atomic
def cancel_agreement(rental, user, reason):
    """Cancel a non-approved agreement and atomically release its assets."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A cancellation reason is required."})
    rental = Rental.objects.select_for_update().get(pk=rental.pk)
    if rental.status not in (Rental.DRAFT, Rental.PENDING_APPROVAL, Rental.REJECTED):
        raise ValidationError({"detail": "Only a draft, pending, or rejected agreement can be cancelled."})
    rental.approvals.filter(status=RentalApproval.PENDING).update(status=RentalApproval.REVOKED)
    RentalAsset.objects.filter(
        rental_lines__rental=rental,
        status=RentalAsset.RESERVED,
    ).update(status=RentalAsset.AVAILABLE)
    rental.status = Rental.CANCELLED
    rental.save(update_fields=["status"])
    _record_event(
        rental,
        RentalEvent.AGREEMENT_CANCELLED,
        actor=user,
        metadata={"reason": reason},
    )
    return rental


@transaction.atomic
def close_agreement(rental, user, reason):
    """Close an approved/active agreement and return its devices to inventory."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A closure reason is required."})
    rental = Rental.objects.select_for_update().get(pk=rental.pk)
    if rental.status not in (Rental.APPROVED, Rental.ACTIVE):
        raise ValidationError({"detail": "Only an approved or active agreement can be closed."})
    RentalAsset.objects.filter(
        rental_lines__rental=rental,
        status=RentalAsset.RENTED,
    ).update(status=RentalAsset.AVAILABLE)
    rental.status = Rental.CLOSED
    rental.save(update_fields=["status"])
    _record_event(
        rental,
        RentalEvent.AGREEMENT_CLOSED,
        actor=user,
        metadata={"reason": reason},
    )
    return rental
