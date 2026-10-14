import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from crmbook_backend.notify import notify_staff, send_whatsapp, whatsapp_provider, whatsapp_template
from .models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalLine


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


def _normalise_whatsapp_number(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = f"91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        digits = f"91{digits[1:]}"
    return digits if 8 <= len(digits) <= 15 else ""


def build_whatsapp_url(phone, message):
    number = _normalise_whatsapp_number(phone)
    target = f"https://wa.me/{number}" if number else "https://wa.me/"
    return f"{target}?text={quote(message, safe='')}"


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


def _handover_snapshot(line):
    """The device's handover record exactly as the customer approves it."""
    tested_by = line.handover_by
    return {
        "checks": [{"label": label, "ok": line.checks.get(key) is True} for key, label in RentalLine.CHECKS],
        "working_confirmed": line.working_confirmed,
        "condition_notes": line.condition_notes,
        "accessories": [
            {"name": a.get("name", ""), "serial": a.get("serial", "")} for a in (line.accessories or [])
        ],
        "warranty": {
            "included": line.warranty_included,
            "months": line.warranty_months,
            "terms": line.warranty_terms if line.warranty_included else "",
        },
        # ids only -- the files are served through the approval link
        # (RentalApprovalPhotoView checks the id is in this snapshot)
        "photos": [
            {"id": p.id, "kind": p.kind, "label": p.get_kind_display(), "caption": p.caption}
            for p in line.photos.all()
        ],
        "tested_by": (tested_by.get_full_name() or tested_by.username) if tested_by else None,
        "tested_at": line.handover_updated_at.isoformat() if line.handover_updated_at else None,
    }


def _snapshot(rental):
    lines = list(rental.lines.select_related("asset", "handover_by").prefetch_related("photos").order_by("id"))
    if not lines:
        raise ValidationError({"lines": "Add at least one physical rental asset before requesting approval."})
    if any(not line.asset.asset_tag or not line.asset.serial_number for line in lines):
        raise ValidationError({"lines": "Every rental asset requires both an asset tag and serial number."})
    incomplete = {
        f"{line.asset.asset_tag} ({line.description})": line.handover_issues()
        for line in lines if line.handover_issues()
    }
    if incomplete:
        raise ValidationError({
            "handover": "Complete the device handover (condition check, photos, accessories, warranty) before approval.",
            "devices": incomplete,
        })
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
                **_handover_snapshot(line),
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
    previous = rental.approvals.order_by("-version").first()
    version = (previous.version if previous else 0) + 1
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
    approval_url = build_approval_url(raw_token)
    message = approval_link_message(rental, approval_url)
    metadata = {"version": version, "expires_at": approval.expires_at.isoformat(), "channel": "whatsapp"}
    if previous and previous.status == RentalApproval.CHANGES_REQUESTED:
        # this link is staff's answer to the customer's change request
        metadata["responds_to_change_request_version"] = previous.version
    _record_event(rental, RentalEvent.APPROVAL_LINK_CREATED, actor=user, approval=approval, metadata=metadata)
    return approval, approval_url, build_whatsapp_url(rental.party.phone, message)


def _agreement_label(rental):
    return rental.agreement_code or f"RENTAL-{rental.pk}"


def approval_link_message(rental, approval_url):
    """The customer-facing text for an approval link -- shared by the
    manual wa.me link and the WhatsApp API send so both say the same."""
    return (
        f"Hello {rental.party.name}, please review your rental agreement {_agreement_label(rental)}. "
        f"This secure link is valid for 24 hours: {approval_url}"
    )


def send_approval_link_whatsapp(rental, approval_url, user):
    """
    Send an approval link staff already hold through the configured
    WhatsApp provider (Meta Cloud API when WHATSAPP_PROVIDER=meta_cloud).

    Only the token's hash is stored, so the link can't be rebuilt here --
    instead the link staff got from issue_approval_link() is passed back
    and checked: its token must hash to THIS rental's current, unexpired,
    still-pending approval. Nothing new is issued (no second token or
    approval row), and staff can't use this to send arbitrary text.

    Uses the approved template WHATSAPP_TEMPLATE_RENTAL_APPROVAL when
    configured (body {{1}} customer name, {{2}} agreement code, {{3}} link);
    otherwise the free-text message, which Meta only accepts inside the
    customer's 24-hour service window.

    The result is recorded on the link's "approval link created" audit
    event; a second send of an already-accepted link is refused so a
    double click can't message the customer twice.
    """
    raw_token = (approval_url or "").rstrip("/").rsplit("/", 1)[-1]
    if not raw_token or len(raw_token) > 200:
        raise ValidationError({"detail": "That isn't an approval link for this agreement."})
    with transaction.atomic():
        approval = (
            RentalApproval.objects.select_for_update().select_related("rental__party")
            .filter(rental=rental, token_hash=approval_token_hash(raw_token)).first()
        )
        if not approval:
            raise ValidationError({"detail": "That isn't an approval link for this agreement."})
        if approval.effective_status != RentalApproval.PENDING:
            raise ValidationError({"detail": "This approval link is no longer active -- generate a new one."})
        event = (
            RentalEvent.objects.select_for_update()
            .filter(rental=rental, approval=approval, event_type=RentalEvent.APPROVAL_LINK_CREATED)
            .order_by("-id").first()
        )
        previous = (event.metadata or {}).get("whatsapp_api") if event else None
        if previous and previous.get("status") == "sent":
            raise RentalApprovalConflict("This link was already sent through WhatsApp.")

        rental = approval.rental
        party = rental.party
        template = whatsapp_template("rental_approval", [party.name, _agreement_label(rental), build_approval_url(raw_token)])
        result = send_whatsapp(party.phone, approval_link_message(rental, build_approval_url(raw_token)), template=template)
        delivery = {
            "status": result.get("status"),
            "provider": whatsapp_provider(),
            "provider_id": result.get("provider_id"),
            "template": template["name"] if template else None,
            "reason": result.get("reason"),
            "error_code": result.get("error_code"),
            "at": timezone.now().isoformat(),
            "by": user.pk if user else None,
        }
        if event:
            event.metadata = {**(event.metadata or {}), "whatsapp_api": delivery}
            event.save(update_fields=["metadata"])
        if result.get("provider_id"):
            from portal.models import WhatsAppDeliveryLog

            WhatsAppDeliveryLog.objects.create(
                party=party, provider_message_id=result["provider_id"], status=WhatsAppDeliveryLog.SENT,
            )
    return {key: delivery[key] for key in ("status", "provider", "provider_id", "template", "reason", "error_code")}


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


CHANGE_REQUEST_MAX_LENGTH = 500


def _clean_change_request(message):
    message = (message or "").strip()
    if not message:
        raise ValidationError({"reason": "Tell us what you would like changed."})
    if len(message) > CHANGE_REQUEST_MAX_LENGTH:
        raise ValidationError({"reason": f"Keep the change request under {CHANGE_REQUEST_MAX_LENGTH} characters."})
    return message


def customer_request_changes(raw_token, message, ip_address=None, user_agent=""):
    """
    The customer asks for changes instead of approving or rejecting.

    Policy: one change request per link. The link moves to
    CHANGES_REQUESTED and accepts no further decision; the agreement is
    NOT decided -- the rental stays awaiting approval and its assets stay
    reserved. Staff answer by revising the agreement and issuing a new
    link (a new immutable snapshot/version). Re-submitting on the same
    link (double tap, retry after a dropped response) returns the
    recorded request unchanged, without a second audit event.
    """
    message = _clean_change_request(message)
    try:
        with transaction.atomic():
            approval = get_public_approval(raw_token, for_update=True)
            if approval.status == RentalApproval.CHANGES_REQUESTED:
                return approval
            if approval.status in (RentalApproval.APPROVED, RentalApproval.REJECTED):
                raise RentalApprovalConflict("A final decision has already been recorded for this agreement.")
            if approval.status != RentalApproval.PENDING:
                raise RentalApprovalLinkGone()
            rental = Rental.objects.select_for_update().select_related("party").get(pk=approval.rental_id)
            if rental.status != Rental.PENDING_APPROVAL:
                raise RentalApprovalLinkGone()
            now = timezone.now()
            updated = RentalApproval.objects.filter(pk=approval.pk, status=RentalApproval.PENDING).update(
                status=RentalApproval.CHANGES_REQUESTED,
                source=RentalApproval.CUSTOMER,
                reason=message,
                decided_at=now,
                decided_ip=ip_address,
                decided_user_agent=(user_agent or "")[:300],
            )
            if updated != 1:
                raise RentalApprovalConflict()
            approval.refresh_from_db()
            _record_event(rental, RentalEvent.CHANGES_REQUESTED, approval=approval, metadata={
                "message": message,
                "source": RentalApproval.CUSTOMER,
                "channel": "secure_link",
                "version": approval.version,
                "requested_at": now.isoformat(),
            })
            label = rental.agreement_code or f"RENTAL-{rental.pk}"
            notify_staff(
                "rental_changes_requested",
                f"Changes requested on rental agreement {label}",
                f"{rental.party.name} asked for changes to rental agreement {label} (link v{approval.version}): {message}",
            )
            return approval
    except IntegrityError as exc:
        raise RentalApprovalConflict() from exc


def customer_decide(raw_token, decision, consent=False, reason="", ip_address=None, user_agent=""):
    if decision == "request_changes":
        return customer_request_changes(raw_token, reason, ip_address=ip_address, user_agent=user_agent)
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose approve, reject, or request changes."})
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
            if approval.status == RentalApproval.CHANGES_REQUESTED:
                raise RentalApprovalConflict(
                    "You asked for changes on this link. We'll send you a revised agreement on a new link."
                )
            if approval.status != RentalApproval.PENDING:
                raise RentalApprovalLinkGone()
            if RentalApproval.objects.filter(rental=approval.rental, status=RentalApproval.APPROVED).exclude(pk=approval.pk).exists():
                raise RentalApprovalConflict()
            updated = RentalApproval.objects.filter(pk=approval.pk, status=RentalApproval.PENDING).update(
                status=desired_status,
                source=RentalApproval.CUSTOMER,
                reason=(reason or "").strip(),
                decided_at=timezone.now(),
                decided_ip=ip_address,
                decided_user_agent=(user_agent or "")[:300],
            )
            if updated != 1:
                raise RentalApprovalConflict()
            approval.refresh_from_db()
            approval.rental.status = Rental.APPROVED if desired_status == RentalApproval.APPROVED else Rental.REJECTED
            approval.rental.save(update_fields=["status"])
            asset_status = RentalAsset.RENTED if desired_status == RentalApproval.APPROVED else RentalAsset.AVAILABLE
            RentalAsset.objects.filter(rental_lines__rental=approval.rental).update(status=asset_status)
            _record_event(approval.rental, RentalEvent.APPROVAL_DECIDED, approval=approval, metadata={"decision": desired_status, "source": RentalApproval.CUSTOMER})
            if desired_status == RentalApproval.APPROVED:
                rental = approval.rental
                label = rental.agreement_code or f"RENTAL-{rental.pk}"
                notify_staff(
                    "rental_approved",
                    f"Rental agreement approved -- {label}",
                    f"{rental.party.name} approved rental agreement {label} ({rental.product_label}, ₹{rental.total_monthly_fee}/month).",
                )
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


HANDOVER_EDITABLE = (Rental.DRAFT, Rental.PENDING_APPROVAL, Rental.REJECTED)


@transaction.atomic
def handover_changed(rental, user, what):
    """
    Called after any change to a device's handover record. Once a
    customer is looking at a link, they must never approve details that
    have since changed -- so a pending link is withdrawn and the
    agreement goes back to draft for a fresh link.
    """
    rental = Rental.objects.select_for_update().get(pk=rental.pk)
    revoked = rental.approvals.filter(status=RentalApproval.PENDING).update(status=RentalApproval.REVOKED)
    if rental.status == Rental.PENDING_APPROVAL:
        rental.status = Rental.DRAFT
        rental.save(update_fields=["status"])
    _record_event(rental, RentalEvent.HANDOVER_UPDATED, actor=user, metadata={"what": what, "pending_link_revoked": bool(revoked)})
    return bool(revoked)
