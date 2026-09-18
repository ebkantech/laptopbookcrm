from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from rentals.models import Rental, RentalApproval, RentalAsset, RentalEvent
from rentals.services import RentalApprovalConflict, RentalApprovalLinkGone
from repairs.models import (
    Notification,
    RepairApproval,
    RepairOrderApproval,
    RepairTicketEvent,
)
from repairs.services import ApprovalConflict, ApprovalLinkGone, _record_order_decision


def decide_rental(approval, decision, consent=False, reason="", actor=None):
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose either approve or reject."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed the rental agreement and charges."})
    try:
        with transaction.atomic():
            approval = RentalApproval.objects.select_for_update().select_related("rental").get(pk=approval.pk)
            desired = RentalApproval.APPROVED if decision == "approve" else RentalApproval.REJECTED
            if approval.status in (RentalApproval.APPROVED, RentalApproval.REJECTED):
                if approval.status == desired:
                    return approval
                raise RentalApprovalConflict("A different final decision has already been recorded.")
            if approval.status != RentalApproval.PENDING or (
                approval.expires_at and timezone.now() >= approval.expires_at
            ):
                if approval.status == RentalApproval.PENDING:
                    RentalApproval.objects.filter(pk=approval.pk).update(status=RentalApproval.EXPIRED)
                raise RentalApprovalLinkGone()
            if RentalApproval.objects.filter(
                rental=approval.rental, status=RentalApproval.APPROVED
            ).exclude(pk=approval.pk).exists():
                raise RentalApprovalConflict()
            now = timezone.now()
            updated = RentalApproval.objects.filter(pk=approval.pk, status=RentalApproval.PENDING).update(
                status=desired,
                source=RentalApproval.CUSTOMER,
                decided_by=actor,
                reason=(reason or "").strip(),
                decided_at=now,
            )
            if updated != 1:
                raise RentalApprovalConflict()
            approval.refresh_from_db()
            approval.rental.status = Rental.APPROVED if desired == RentalApproval.APPROVED else Rental.REJECTED
            approval.rental.save(update_fields=["status"])
            asset_status = RentalAsset.RENTED if desired == RentalApproval.APPROVED else RentalAsset.AVAILABLE
            RentalAsset.objects.filter(rental_lines__rental=approval.rental).update(status=asset_status)
            RentalEvent.objects.create(
                rental=approval.rental,
                approval=approval,
                event_type=RentalEvent.APPROVAL_DECIDED,
                actor=actor,
                metadata={"decision": desired, "source": RentalApproval.CUSTOMER},
            )
            return approval
    except IntegrityError as exc:
        raise RentalApprovalConflict() from exc


def decide_repair(approval, decision, consent=False, reason="", actor=None):
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose either approve or reject."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed the final work and cost."})
    try:
        with transaction.atomic():
            approval = RepairApproval.objects.select_for_update().select_related("estimate__ticket").get(pk=approval.pk)
            desired = RepairApproval.APPROVED if decision == "approve" else RepairApproval.REJECTED
            if approval.status in (RepairApproval.APPROVED, RepairApproval.REJECTED):
                if approval.status == desired:
                    return approval
                raise ApprovalConflict("A different final decision has already been recorded.")
            if approval.status != RepairApproval.PENDING or not approval.estimate.is_current or (
                approval.expires_at and timezone.now() >= approval.expires_at
            ):
                if approval.status == RepairApproval.PENDING:
                    RepairApproval.objects.filter(pk=approval.pk).update(status=RepairApproval.EXPIRED)
                raise ApprovalLinkGone()
            if approval.estimate.approvals.filter(status=RepairApproval.APPROVED).exclude(pk=approval.pk).exists():
                raise ApprovalConflict()
            now = timezone.now()
            updated = RepairApproval.objects.filter(pk=approval.pk, status=RepairApproval.PENDING).update(
                status=desired,
                source=RepairApproval.CUSTOMER,
                decided_by=actor,
                reason=(reason or "").strip(),
                decided_at=now,
            )
            if updated != 1:
                raise ApprovalConflict()
            approval.refresh_from_db()
            RepairTicketEvent.objects.create(
                ticket=approval.estimate.ticket,
                estimate=approval.estimate,
                event_type=RepairTicketEvent.APPROVAL_DECIDED,
                actor=actor,
                metadata={"decision": desired, "source": RepairApproval.CUSTOMER},
            )
            Notification.objects.create(
                ticket=approval.estimate.ticket,
                channel=Notification.WHATSAPP,
                text=f"Customer {desired} final estimate v{approval.estimate.version} for {approval.estimate.ticket.code}.",
            )
            return approval
    except IntegrityError as exc:
        raise ApprovalConflict() from exc


def decide_repair_order(approval, decision, consent=False, reason="", actor=None):
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Choose either approve or reject."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed every device, work line, and cost."})
    try:
        with transaction.atomic():
            approval = RepairOrderApproval.objects.select_for_update().select_related("order").get(pk=approval.pk)
            desired = RepairOrderApproval.APPROVED if decision == "approve" else RepairOrderApproval.REJECTED
            if approval.status in (RepairOrderApproval.APPROVED, RepairOrderApproval.REJECTED):
                if approval.status == desired:
                    return approval
                raise ApprovalConflict("A different final decision has already been recorded.")
            if approval.status != RepairOrderApproval.PENDING or (
                approval.expires_at and timezone.now() >= approval.expires_at
            ):
                if approval.status == RepairOrderApproval.PENDING:
                    RepairOrderApproval.objects.filter(pk=approval.pk).update(status=RepairOrderApproval.EXPIRED)
                raise ApprovalLinkGone()
            return _record_order_decision(
                approval,
                RepairOrderApproval.CUSTOMER,
                decision,
                reason=(reason or "").strip(),
                user=actor,
            )
    except IntegrityError as exc:
        raise ApprovalConflict() from exc
