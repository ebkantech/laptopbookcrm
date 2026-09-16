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

from .models import (
    DEFAULT_APPROVAL_TERMS,
    Notification,
    RepairApproval,
    RepairEstimate,
    RepairEstimateLine,
    RepairOrder,
    RepairOrderApproval,
    RepairTicket,
    RepairTicketEvent,
)


APPROVAL_LINK_TTL = timedelta(hours=24)


class ApprovalLinkGone(APIException):
    status_code = 410
    default_detail = "This approval link is invalid or has expired."
    default_code = "approval_link_gone"


class ApprovalConflict(APIException):
    status_code = 409
    default_detail = "A final decision has already been recorded for this estimate."
    default_code = "approval_conflict"


def approval_token_hash(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _record_event(ticket, event_type, actor=None, estimate=None, metadata=None):
    return RepairTicketEvent.objects.create(ticket=ticket, estimate=estimate, event_type=event_type, actor=actor, metadata=metadata or {})


def _expire_pending_links(estimate, now=None):
    now = now or timezone.now()
    return estimate.approvals.filter(status=RepairApproval.PENDING, expires_at__lte=now).update(status=RepairApproval.EXPIRED)


def _current_estimate(ticket):
    return RepairEstimate.objects.select_for_update().filter(ticket=ticket, is_current=True).first()


def _normalise_whatsapp_number(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = f"91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        digits = f"91{digits[1:]}"
    return digits if 8 <= len(digits) <= 15 else ""


def build_approval_url(raw_token):
    return f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/repair-approval/{raw_token}"


def build_order_approval_url(raw_token):
    return f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/repair-order-approval/{raw_token}"


def build_whatsapp_url(phone, message):
    number = _normalise_whatsapp_number(phone)
    target = f"https://wa.me/{number}" if number else "https://wa.me/"
    return f"{target}?text={quote(message, safe='')}"


@transaction.atomic
def finalize_estimate(ticket, user, lines, terms=""):
    ticket = RepairTicket.objects.select_for_update().select_related("party").get(pk=ticket.pk)
    if ticket.status != RepairTicket.DIAGNOSING:
        raise ValidationError({"detail": "The final estimate can only be prepared while the ticket is Diagnosing."})
    if not lines:
        raise ValidationError({"lines": "Add at least one work or cost line."})

    current = _current_estimate(ticket)
    if current and current.is_approved:
        raise ValidationError({"detail": "The approved estimate is locked. Later changes are managed separately by the client."})
    if current:
        _expire_pending_links(current)
        current.approvals.filter(status=RepairApproval.PENDING).update(status=RepairApproval.REVOKED)
        current.is_current = False
        current.save(update_fields=["is_current"])
    if ticket.order_id:
        ticket.order.approvals.filter(status=RepairOrderApproval.PENDING).update(
            status=RepairOrderApproval.REVOKED
        )

    version = (RepairEstimate.objects.filter(ticket=ticket).aggregate(value=Max("version"))["value"] or 0) + 1
    prepared_lines, selected_services, total_amount = [], [], 0
    for line in lines:
        service = line.get("service")
        description = (line.get("description") or (service.label if service else "")).strip()
        quantity = line.get("quantity", 1)
        unit_price = line.get("unit_price") if line.get("unit_price") is not None else (service.charge if service else None)
        if not description:
            raise ValidationError({"lines": "Every estimate line needs a description."})
        if quantity < 1:
            raise ValidationError({"lines": "Quantity must be at least 1."})
        if unit_price is None or unit_price < 0:
            raise ValidationError({"lines": "Unit price must be zero or greater."})
        total_amount += quantity * unit_price
        prepared_lines.append({"service": service, "description": description, "quantity": quantity, "unit_price": unit_price})
        if service:
            selected_services.append(service)

    estimate = RepairEstimate.objects.create(
        ticket=ticket, version=version, customer_name=ticket.party.name, customer_phone=ticket.party.phone,
        device_brand=ticket.brand, device_model=ticket.model_name, device_serial=ticket.serial,
        reported_issue=ticket.issue, total_amount=total_amount, advance_paid=ticket.advance_paid,
        terms=(terms or DEFAULT_APPROVAL_TERMS).strip(), created_by=user,
    )
    RepairEstimateLine.objects.bulk_create([RepairEstimateLine(estimate=estimate, **line) for line in prepared_lines])
    ticket.services.set(selected_services)
    _record_event(ticket, RepairTicketEvent.ESTIMATE_FINALIZED, actor=user, estimate=estimate, metadata={"version": version, "line_count": len(prepared_lines), "total_amount": total_amount})
    return estimate


@transaction.atomic
def issue_approval_link(ticket, user):
    ticket = RepairTicket.objects.select_for_update().select_related("party").get(pk=ticket.pk)
    estimate = _current_estimate(ticket)
    if not estimate:
        raise ValidationError({"detail": "Finalize the exact repair work and cost first."})
    if estimate.is_approved:
        raise ValidationError({"detail": "This estimate already has a final approval."})

    now = timezone.now()
    _expire_pending_links(estimate, now)
    estimate.approvals.filter(status=RepairApproval.PENDING).update(status=RepairApproval.REVOKED)
    raw_token = secrets.token_urlsafe(32)
    approval = RepairApproval.objects.create(
        estimate=estimate, token_hash=approval_token_hash(raw_token), status=RepairApproval.PENDING,
        sent_to_phone=estimate.customer_phone, requested_by=user, created_at=now, expires_at=now + APPROVAL_LINK_TTL,
    )
    approval_url = build_approval_url(raw_token)
    message = f"Hello {estimate.customer_name}, please review the final repair estimate for {ticket.code} (INR {estimate.total_amount}). This secure link is valid for 24 hours: {approval_url}"
    Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=f"Secure approval link generated for {ticket.code}; valid for 24 hours.")
    _record_event(ticket, RepairTicketEvent.APPROVAL_LINK_CREATED, actor=user, estimate=estimate, metadata={"expires_at": approval.expires_at.isoformat(), "channel": "whatsapp"})
    return approval, approval_url, build_whatsapp_url(estimate.customer_phone, message)


def approve_on_behalf(ticket, user, reason):
    if not user.has_perm_code("repairs.approve"):
        raise PermissionDenied("You do not have permission to approve repair estimates.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required for Admin or Super Admin approval."})
    try:
        with transaction.atomic():
            ticket = RepairTicket.objects.select_for_update().get(pk=ticket.pk)
            estimate = _current_estimate(ticket)
            if not estimate:
                raise ValidationError({"detail": "Finalize the exact repair work and cost first."})
            if estimate.is_approved:
                raise ApprovalConflict()
            now = timezone.now()
            _expire_pending_links(estimate, now)
            if estimate.approvals.filter(status=RepairApproval.REJECTED, source=RepairApproval.CUSTOMER).exists() and not user.is_superuser:
                raise ValidationError({"detail": "The customer rejected this estimate. Only a Super Admin can override it."})
            estimate.approvals.filter(status=RepairApproval.PENDING).update(status=RepairApproval.REVOKED)
            source = RepairApproval.SUPERADMIN if user.is_superuser else RepairApproval.ADMIN
            approval = RepairApproval.objects.create(estimate=estimate, status=RepairApproval.APPROVED, source=source, sent_to_phone=estimate.customer_phone, requested_by=user, decided_by=user, reason=reason, created_at=now, decided_at=now)
            _record_event(ticket, RepairTicketEvent.APPROVAL_DECIDED, actor=user, estimate=estimate, metadata={"decision": "approved", "source": source, "reason": reason})
            return approval
    except IntegrityError as exc:
        raise ApprovalConflict() from exc


def get_public_approval(raw_token, for_update=False):
    if not raw_token or len(raw_token) > 200:
        raise NotFound("This approval link is invalid or has expired.")
    queryset = RepairApproval.objects.select_related("estimate__ticket")
    if for_update:
        queryset = queryset.select_for_update()
    try:
        approval = queryset.get(token_hash=approval_token_hash(raw_token))
    except RepairApproval.DoesNotExist as exc:
        raise NotFound("This approval link is invalid or has expired.") from exc
    now = timezone.now()
    if approval.expires_at and now >= approval.expires_at:
        if approval.status == RepairApproval.PENDING:
            RepairApproval.objects.filter(pk=approval.pk, status=RepairApproval.PENDING).update(status=RepairApproval.EXPIRED)
        raise ApprovalLinkGone()
    if approval.status in (RepairApproval.EXPIRED, RepairApproval.REVOKED) or not approval.estimate.is_current:
        raise ApprovalLinkGone()
    return approval


def customer_decide(raw_token, decision, consent=False, reason=""):
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose either approve or reject."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed the final work and cost."})
    try:
        with transaction.atomic():
            approval = get_public_approval(raw_token, for_update=True)
            desired_status = RepairApproval.APPROVED if decision == "approve" else RepairApproval.REJECTED
            if approval.status in (RepairApproval.APPROVED, RepairApproval.REJECTED):
                if approval.status == desired_status:
                    return approval
                raise ApprovalConflict("A different final decision has already been recorded.")
            if approval.status != RepairApproval.PENDING:
                raise ApprovalLinkGone()
            estimate = approval.estimate
            if estimate.approvals.filter(status=RepairApproval.APPROVED).exclude(pk=approval.pk).exists():
                RepairApproval.objects.filter(pk=approval.pk, status=RepairApproval.PENDING).update(status=RepairApproval.REVOKED)
                raise ApprovalConflict()
            now = timezone.now()
            if RepairApproval.objects.filter(pk=approval.pk, status=RepairApproval.PENDING).update(status=desired_status, source=RepairApproval.CUSTOMER, reason=(reason or "").strip(), decided_at=now) != 1:
                raise ApprovalConflict()
            approval.status, approval.source, approval.reason, approval.decided_at = desired_status, RepairApproval.CUSTOMER, (reason or "").strip(), now
            _record_event(estimate.ticket, RepairTicketEvent.APPROVAL_DECIDED, estimate=estimate, metadata={"decision": desired_status, "source": RepairApproval.CUSTOMER})
            Notification.objects.create(ticket=estimate.ticket, channel=Notification.WHATSAPP, text=f"Customer {desired_status} final estimate v{estimate.version} for {estimate.ticket.code}.")
            return approval
    except IntegrityError as exc:
        raise ApprovalConflict() from exc


def _repair_order_snapshot(order, allow_customer_rejection=False):
    tickets = list(
        order.tickets.select_related("party").prefetch_related(
            "estimates__lines", "estimates__approvals"
        ).order_by("id")
    )
    if len(tickets) < 2:
        raise ValidationError({"detail": "Combined approval is only used for bulk repair orders with two or more devices."})

    devices = []
    for ticket in tickets:
        estimate = ticket.current_estimate
        if not estimate:
            raise ValidationError({
                "detail": f"Finalize the exact work and cost for {ticket.code} before creating the combined link."
            })
        if estimate.is_approved:
            raise ValidationError({"detail": f"{ticket.code} already has a final approval."})
        if (
            not allow_customer_rejection
            and estimate.approvals.filter(
                status=RepairApproval.REJECTED, source=RepairApproval.CUSTOMER
            ).exists()
        ):
            raise ValidationError({
                "detail": f"{ticket.code} was rejected by the customer. Internal Admin/Super Admin handling is required."
            })
        devices.append({
            "ticket_id": ticket.pk,
            "ticket_code": ticket.code,
            "estimate_id": estimate.pk,
            "estimate_version": estimate.version,
            "brand": estimate.device_brand,
            "model_name": estimate.device_model,
            "serial": estimate.device_serial,
            "reported_issue": estimate.reported_issue,
            "lines": [
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "line_total": line.line_total,
                }
                for line in estimate.lines.all()
            ],
            "total_amount": estimate.total_amount,
        })

    return {
        "order_code": order.code,
        "customer": {
            "name": order.party.name,
            "classification": order.party.customer_classification,
        },
        "repair_type": "bulk",
        "currency": "INR",
        "terms": DEFAULT_APPROVAL_TERMS,
        "devices": devices,
        "grand_total": sum(device["total_amount"] for device in devices),
    }


@transaction.atomic
def issue_order_approval_link(order, user):
    order = RepairOrder.objects.select_for_update().select_related("party").get(pk=order.pk)
    if order.approvals.filter(status=RepairOrderApproval.APPROVED).exists():
        raise ValidationError({"detail": "This repair order already has a final approval."})
    now = timezone.now()
    order.approvals.filter(
        status=RepairOrderApproval.PENDING, expires_at__lte=now
    ).update(status=RepairOrderApproval.EXPIRED)
    order.approvals.filter(status=RepairOrderApproval.PENDING).update(status=RepairOrderApproval.REVOKED)
    snapshot = _repair_order_snapshot(order)

    estimate_ids = [device["estimate_id"] for device in snapshot["devices"]]
    RepairApproval.objects.filter(
        estimate_id__in=estimate_ids, status=RepairApproval.PENDING
    ).update(status=RepairApproval.REVOKED)

    version = (order.approvals.aggregate(value=Max("version"))["value"] or 0) + 1
    raw_token = secrets.token_urlsafe(32)
    approval = RepairOrderApproval.objects.create(
        order=order,
        version=version,
        snapshot=snapshot,
        token_hash=approval_token_hash(raw_token),
        requested_by=user,
        expires_at=now + APPROVAL_LINK_TTL,
    )
    for ticket in order.tickets.all():
        _record_event(
            ticket,
            RepairTicketEvent.APPROVAL_LINK_CREATED,
            actor=user,
            estimate=ticket.current_estimate,
            metadata={
                "order_code": order.code,
                "combined": True,
                "version": version,
                "expires_at": approval.expires_at.isoformat(),
            },
        )
    return approval, build_order_approval_url(raw_token)


def get_public_order_approval(raw_token, for_update=False):
    if not raw_token or len(raw_token) > 200:
        raise NotFound("This approval link is invalid or has expired.")
    queryset = RepairOrderApproval.objects.select_related("order")
    if for_update:
        queryset = queryset.select_for_update()
    try:
        approval = queryset.get(token_hash=approval_token_hash(raw_token))
    except RepairOrderApproval.DoesNotExist as exc:
        raise NotFound("This approval link is invalid or has expired.") from exc
    now = timezone.now()
    if approval.expires_at and now >= approval.expires_at:
        if approval.status == RepairOrderApproval.PENDING:
            RepairOrderApproval.objects.filter(
                pk=approval.pk, status=RepairOrderApproval.PENDING
            ).update(status=RepairOrderApproval.EXPIRED)
        raise ApprovalLinkGone()
    if approval.status in (RepairOrderApproval.EXPIRED, RepairOrderApproval.REVOKED):
        raise ApprovalLinkGone()
    return approval


def _record_order_decision(approval, source, decision, reason="", user=None):
    desired_status = (
        RepairOrderApproval.APPROVED if decision == "approve" else RepairOrderApproval.REJECTED
    )
    snapshot_devices = approval.snapshot.get("devices", [])
    estimate_ids = [device["estimate_id"] for device in snapshot_devices]
    estimates = {
        estimate.pk: estimate
        for estimate in RepairEstimate.objects.select_for_update().select_related("ticket").filter(
            pk__in=estimate_ids
        )
    }
    if len(estimates) != len(estimate_ids):
        raise ApprovalConflict("One or more repair estimates no longer exist.")
    for device in snapshot_devices:
        estimate = estimates[device["estimate_id"]]
        if not estimate.is_current or estimate.version != device["estimate_version"]:
            raise ApprovalConflict("The repair work changed after this link was created.")
        if estimate.approvals.filter(status=RepairApproval.APPROVED).exists():
            raise ApprovalConflict()

    now = timezone.now()
    if RepairOrderApproval.objects.filter(
        pk=approval.pk, status=RepairOrderApproval.PENDING
    ).update(
        status=desired_status,
        source=source,
        reason=reason,
        decided_by=user,
        decided_at=now,
    ) != 1:
        raise ApprovalConflict()

    child_status = RepairApproval.APPROVED if decision == "approve" else RepairApproval.REJECTED
    for estimate in estimates.values():
        estimate.approvals.filter(status=RepairApproval.PENDING).update(status=RepairApproval.REVOKED)
        RepairApproval.objects.create(
            estimate=estimate,
            order_approval=approval,
            status=child_status,
            source=source,
            sent_to_phone=estimate.customer_phone,
            requested_by=approval.requested_by,
            decided_by=user,
            reason=reason,
            created_at=now,
            decided_at=now,
        )
        _record_event(
            estimate.ticket,
            RepairTicketEvent.APPROVAL_DECIDED,
            actor=user,
            estimate=estimate,
            metadata={
                "decision": child_status,
                "source": source,
                "combined": True,
                "order_code": approval.order.code,
                "reason": reason,
            },
        )
    approval.status = desired_status
    approval.source = source
    approval.reason = reason
    approval.decided_by = user
    approval.decided_at = now
    return approval


def customer_decide_order(raw_token, decision, consent=False, reason=""):
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose either approve or reject."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed every device, work line, and cost."})
    reason = (reason or "").strip()
    try:
        with transaction.atomic():
            approval = get_public_order_approval(raw_token, for_update=True)
            desired_status = (
                RepairOrderApproval.APPROVED if decision == "approve" else RepairOrderApproval.REJECTED
            )
            if approval.status in (RepairOrderApproval.APPROVED, RepairOrderApproval.REJECTED):
                if approval.status == desired_status:
                    return approval
                raise ApprovalConflict("A different final decision has already been recorded.")
            return _record_order_decision(
                approval, RepairOrderApproval.CUSTOMER, decision, reason=reason
            )
    except IntegrityError as exc:
        raise ApprovalConflict() from exc


def approve_order_on_behalf(order, user, reason):
    if not user.has_perm_code("repairs.approve"):
        raise PermissionDenied("You do not have permission to approve repair orders.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required for Admin or Super Admin approval."})
    try:
        with transaction.atomic():
            order = RepairOrder.objects.select_for_update().get(pk=order.pk)
            if order.approvals.filter(status=RepairOrderApproval.APPROVED).exists():
                raise ApprovalConflict()
            now = timezone.now()
            order.approvals.filter(status=RepairOrderApproval.PENDING).update(
                status=RepairOrderApproval.REVOKED
            )
            snapshot = _repair_order_snapshot(order, allow_customer_rejection=True)
            version = (order.approvals.aggregate(value=Max("version"))["value"] or 0) + 1
            source = RepairOrderApproval.SUPERADMIN if user.is_superuser else RepairOrderApproval.ADMIN
            approval = RepairOrderApproval.objects.create(
                order=order,
                version=version,
                snapshot=snapshot,
                status=RepairOrderApproval.PENDING,
                requested_by=user,
            )
            return _record_order_decision(
                approval, source, "approve", reason=reason, user=user
            )
    except IntegrityError as exc:
        raise ApprovalConflict() from exc
