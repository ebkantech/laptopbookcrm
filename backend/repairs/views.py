from datetime import date
import json
from uuid import uuid4

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasPerm
from accounts.store_scope import StoreScope, StoreScopedMixin
from catalog.models import Service
from catalog.views import part_stock_prefetch
from crmbook_backend.notify import notify_staff, send_email, send_whatsapp, whatsapp_provider
from sales.models import Invoice
from sales.payments import pay_note
from sales.services import cancel_invoice, create_invoice

from .billing import advance_amount, raise_advance_invoice, reconcile_delivery
from .models import Notification, RepairOrder, RepairReopen, RepairReopenItem, RepairRevision, RepairTicket, RepairTicketEvent
from .serializers import (
    CreateRepairOrderSerializer,
    DecideRevisionSerializer,
    DiagnoseSerializer,
    FinalizeEstimateSerializer,
    ProposeRevisionSerializer,
    PublicApprovalDecisionSerializer,
    PublicRepairApprovalSerializer,
    PublicRepairOrderApprovalSerializer,
    RepairOrderSerializer,
    RepairTicketSerializer,
    StaffApprovalSerializer,
)
from .services import (
    accept_revision,
    build_whatsapp_url,
    approve_on_behalf,
    approve_order_on_behalf,
    customer_decide,
    customer_decide_order,
    decline_revision,
    finalize_estimate,
    get_public_approval,
    get_public_order_approval,
    issue_approval_link,
    issue_order_approval_link,
    log_whatsapp,
    order_link_message,
    propose_revision,
    report_diagnosis,
    send_approval_link_whatsapp,
    send_order_approval_link_whatsapp,
    stamp_stage,
)


def _private_response(data, status_code=status.HTTP_200_OK):
    response = Response(data, status=status_code)
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _audit_value(value):
    if hasattr(value, "all") and hasattr(value, "values_list"):
        return list(value.values_list("pk", flat=True))
    if hasattr(value, "pk"):
        return value.pk
    return value


def _notify_party(party, subject, text):
    """
    Fires the actual WhatsApp + email send for a ticket-related update,
    on top of the Notification row each call site already creates as
    the durable record. See crmbook_backend/notify.py.
    """
    send_whatsapp(party.phone, text)
    send_email(party.email, subject, text)


def _issue_link_payload(ticket, user):
    approval, url, whatsapp_url = issue_approval_link(ticket, user)
    estimate = ticket.current_estimate
    return {"url": url, "whatsapp_url": whatsapp_url, "expires_at": approval.expires_at,
            "total": estimate.total_amount if estimate else None, "whatsapp_provider": whatsapp_provider(),
            "send_path": f"/tickets/{ticket.pk}/approval-link/send-whatsapp/"}


def _order_link_payload(order, approval, url):
    return {"url": url, "whatsapp_url": build_whatsapp_url(order.party.phone, order_link_message(order, url)),
            "expires_at": approval.expires_at, "whatsapp_provider": whatsapp_provider(),
            "send_path": f"/repair-orders/{order.pk}/approval-link/send-whatsapp/"}


def _booking_lines(services, lines):
    """The estimate lines typed in at booking; only if none were typed (an
    older client) fall back to the chosen catalogue services' list prices."""
    if lines:
        return [{"service": l.get("service"), "description": l["description"], "quantity": l["quantity"], "unit_price": l.get("unit_price")} for l in lines]
    return [{"service": s, "description": s.label, "quantity": 1, "unit_price": s.charge} for s in services]


def _booking_advance(payment, amount, services):
    """Advance asked for at booking: the amount typed in; 25% of the catalogue
    prices only when an older client sends no amount at all."""
    if payment != RepairTicket.ADVANCE:
        return 0
    return amount if amount is not None else advance_amount(services)


def _auto_estimate(ticket, user, services, lines=()):
    """Admin / Super Admin booking a ticket in fixes the estimate there and
    then, so the client's approval link goes out at ticket generation."""
    built = _booking_lines(services, lines)
    if not built or not user.has_perm_code("repairs.approve"):
        return None
    finalize_estimate(ticket, user, built)
    return _issue_link_payload(ticket, user)


def _start_gate(ticket, target, request):
    """Work (In progress) starts only after the repair staff report their
    diagnosis, and not while an estimate revision is unresolved. An Admin /
    Super Admin can override the first with a reason (logged)."""
    if target != RepairTicket.IN_PROGRESS or ticket.status not in (RepairTicket.RECEIVED, RepairTicket.DIAGNOSING):
        return None
    if ticket.pending_revision:
        return Response({"detail": "Estimate revision waiting for Admin review. Resolve it before work starts."}, status=400)
    if ticket.awaiting_diagnosis:
        reason = (request.data.get("override_reason") or "").strip()
        if reason and request.user.has_perm_code("repairs.assign"):
            RepairTicketEvent.objects.create(ticket=ticket, event_type=RepairTicketEvent.STAGE_CHANGED, actor=request.user,
                                             metadata={"override": "started without the staff diagnosis", "reason": reason})
            return None
        return Response({"detail": f"Waiting for {ticket.assigned_to}'s diagnosis. Work starts once they report back.", "code": "awaiting_diagnosis"}, status=400)
    return None


def _order_gate(ticket, target):
    """A job goes in order: given to staff first, and only finished once work
    has been In progress. Applies to everyone, the Super Admin included."""
    if RepairTicket.STAGES.index(target) <= RepairTicket.STAGES.index(ticket.status):
        return None
    if not ticket.assigned_to_id:
        return Response({"detail": "Assign this job to a staff member first.", "code": "needs_assignment"}, status=400)
    if target == RepairTicket.READY and ticket.status != RepairTicket.IN_PROGRESS:
        return Response({"detail": "Move the job to In progress first. It can only be finished after work has started.",
                         "code": "work_not_started"}, status=400)
    return None


def _move(ticket, new_status, actor):
    """Change stage, stamping the work timeline and logging who did it."""
    old = ticket.status
    fields = ["status"] + stamp_stage(ticket, new_status, actor)
    ticket.status = new_status
    ticket.save(update_fields=fields)
    RepairTicketEvent.objects.create(ticket=ticket, event_type=RepairTicketEvent.STAGE_CHANGED, actor=actor,
                                     metadata={"from": old, "to": new_status})


class RepairTicketViewSet(StoreScopedMixin, viewsets.ModelViewSet):
    # Store scope: RepairTicket.stock_point (the drop-off shop).
    queryset = (
        RepairTicket.objects
        .select_related("party", "stock_point", "order")
        .prefetch_related(
            "services__part", "notifications", "invoices", "reopens__items", "reopens__invoice",
            "estimates__lines", "estimates__approvals", "events", "revisions__requested_by", "revisions__decided_by",
            "order__tickets__estimates__lines", "order__tickets__estimates__approvals",
        )
        .all()
    )
    serializer_class = RepairTicketSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "repairs.view", "retrieve": "repairs.view",
        # Repair staff (repairs.manage) receive a job, do it and move it along;
        # booking, billing, reopening and editing a ticket are Admin / Super Admin (repairs.book).
        "create": "repairs.book", "update": "repairs.book",
        "partial_update": "repairs.book", "destroy": "repairs.book",
        "advance": "repairs.manage", "settle": "repairs.book",
        "set_stage": "repairs.manage", "reopen": "repairs.book",
        "finalize_estimate": "repairs.approve", "approval_link": "repairs.approve",
        "approval_link_send_whatsapp": "repairs.approve",
        "revise": "repairs.manage", "diagnose": "repairs.manage", "decide_revision": "repairs.approve",
        "approve_on_behalf": "repairs.approve",
        "assign": "repairs.assign", "staff": "repairs.view",
    }

    def get_queryset(self):
        # nested services carry their part's stock -- this store's rows only
        # Store staff see their store's tickets plus any ticket the Super Admin
        # gave them personally, even one from another store.
        scope = self.store_scope
        qs = RepairTicket.objects.select_related("party", "stock_point", "order", "assigned_to").prefetch_related(
            *self.queryset._prefetch_related_lookups
        )
        user = self.request.user
        # Repair staff (work-only role) see just the jobs given to them -- not the
        # store's other jobs, and not what an Admin has given to someone else.
        worker = user.has_perm_code("repairs.manage") and not any(user.has_perm_code(c) for c in ("repairs.assign", "repairs.book", "repairs.approve"))
        if worker and not user.is_superuser:
            qs = qs.filter(assigned_to=user)
        elif not scope.all:
            qs = qs.filter(Q(stock_point_id=scope.store_id) | Q(assigned_to=user)) if scope.store_id is not None else qs.filter(assigned_to=user)
        qs = qs.prefetch_related(part_stock_prefetch(scope, "services__part__stock"))
        if self.action in ("list", "retrieve", "settle"):
            # a paid bill that didn't deliver its ticket (see reconcile_delivery)
            stuck = list(qs.filter(status=RepairTicket.READY, invoices__is_advance=False, invoices__status__in=("Paid", "Refunded")).distinct())
            if any(reconcile_delivery(t) for t in stuck):
                qs = qs.all()
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        if self.request.query_params.get("mine") == "1":
            qs = qs.filter(assigned_to=self.request.user)
        return qs

    def _require_can_work(self, ticket):
        """A ticket given to someone is theirs to progress; an Admin / Super
        Admin (repairs.assign) can step in when they're unavailable."""
        user = self.request.user
        if ticket.assigned_to_id and ticket.assigned_to_id != user.id and not user.has_perm_code("repairs.assign"):
            raise PermissionDenied(f"This job is assigned to {ticket.assigned_to}. Ask an Admin to take it over or reassign it.")

    def get_object(self):
        ticket = super().get_object()
        if self.action in ("advance", "set_stage", "settle", "reopen", "finalize_estimate", "approval_link", "approval_link_send_whatsapp", "revise", "diagnose", "update", "partial_update"):
            self._require_can_work(ticket)
        return ticket

    @action(detail=False, methods=["get"])
    def staff(self, request):
        """Repair staff who can be given a job: the Super Admin sees every
        store's, an Admin only their own store's."""
        # The Super Admin / Owner doesn't take repair jobs: diagnosis and the work are done by repair staff.
        qs = User.objects.filter(is_active=True, is_superuser=False, role__permissions__codename="repairs.manage").exclude(role__slug="owner").distinct()
        scope = self.store_scope
        if not scope.all:
            qs = qs.filter(stock_point_id=scope.store_id) if scope.store_id is not None else qs.none()
        return Response([{"id": u.id, "name": u.get_full_name() or u.username, "stock_point": u.stock_point_id,
                          "stock_point_name": u.stock_point.name if u.stock_point_id else "No store"}
                         for u in qs.select_related("stock_point").order_by("first_name", "username")])

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Give the ticket to a repair staff member (or take it back with
        assigned_to: null). Super Admin: any store's staff. Admin: staff of
        their own store only. Taking over -- assigning it to yourself -- is how
        an Admin steps in when the assigned person is away."""
        ticket = super().get_object()
        raw = request.data.get("assigned_to")
        if raw in (None, "", 0, "0"):
            target = None
        else:
            try:
                target = User.objects.get(pk=raw, is_active=True)
            except (User.DoesNotExist, TypeError, ValueError):
                raise ValidationError({"assigned_to": "Pick a staff member."})
            if target.is_superuser or (target.role_id and target.role.slug == "owner"):
                raise ValidationError({"assigned_to": "The Super Admin doesn't take repair jobs -- give it to a repair staff member."})
            if not target.has_perm_code("repairs.manage"):
                raise ValidationError({"assigned_to": "That person can't work on repair jobs."})
            scope = self.store_scope
            if not scope.all and target.id != request.user.id and target.stock_point_id != scope.store_id:
                raise ValidationError({"assigned_to": "You can only give jobs to staff of your own store."})
        if ticket.status == RepairTicket.DELIVERED:
            raise ValidationError({"detail": "A delivered ticket can't be reassigned."})
        previous = ticket.assigned_to
        ticket.assigned_to = target
        ticket.assigned_at = timezone.now() if target else None
        ticket.save(update_fields=["assigned_to", "assigned_at"])
        RepairTicketEvent.objects.create(
            ticket=ticket, event_type=RepairTicketEvent.ASSIGNED, actor=request.user,
            metadata={"to": str(target) if target else None, "from": str(previous) if previous else None,
                      "took_over": bool(target and target.id == request.user.id)},
        )
        if target and target.id != request.user.id:
            notify_staff("repair_assigned", f"Repair {ticket.code} assigned to you",
                         f"{ticket.code} ({ticket.brand} {ticket.model_name}, {ticket.party.name}) at {ticket.stock_point.name} was given to {target}.")
            if getattr(target, "phone", ""):
                send_whatsapp(target.phone, f"You have a new repair job {ticket.code}: {ticket.brand} {ticket.model_name} at {ticket.stock_point.name}.")
        return Response(RepairTicketSerializer(self._fresh(ticket)).data)

    def perform_update(self, serializer):
        ticket = self.get_object()
        if ticket.has_repair_approval:
            reason = (self.request.data.get("internal_change_reason") or "").strip()
            if not reason:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    "internal_change_reason": "A reason is required when changing a customer-approved ticket."
                })
            before = {field: _audit_value(getattr(ticket, field)) for field in serializer.validated_data}
            updated = serializer.save()
            after = {field: _audit_value(getattr(updated, field)) for field in serializer.validated_data}
            if before != after:
                RepairTicketEvent.objects.create(
                    ticket=updated,
                    estimate=updated.current_estimate,
                    event_type=RepairTicketEvent.MODIFIED_AFTER_APPROVAL,
                    actor=self.request.user,
                    metadata=json.loads(DjangoJSONEncoder().encode({
                        "reason": reason,
                        "before": before,
                        "after": after,
                    })),
                )
            return
        serializer.save()

    def create(self, request, *args, **kwargs):
        self._approval = None
        response = super().create(request, *args, **kwargs)
        if self._approval:
            response.data["approval"] = self._approval
        return response

    @transaction.atomic
    def perform_create(self, serializer):
        services = serializer.validated_data.get("services", [])
        lines = serializer.validated_data.pop("estimate_lines", [])
        typed_advance = serializer.validated_data.pop("advance_amount", None)
        ticket = serializer.save(code=f"TMP-{uuid4().hex[:16]}", status=RepairTicket.RECEIVED)
        ticket.code = f"RPR-{1044 + ticket.pk}"
        ticket.save(update_fields=["code"])
        device = f"{ticket.brand} {ticket.model_name}"
        wa_text = f"Ticket {ticket.code} created for your {device}. We'll keep you posted."
        pay = ""
        if ticket.payment == RepairTicket.ADVANCE:
            advance_invoice = raise_advance_invoice(ticket, _booking_advance(ticket.payment, typed_advance, services))
            if advance_invoice:
                pay = pay_note(advance_invoice, self.request.user)
                wa_text += f" Advance invoice {advance_invoice.code} for Rs {advance_invoice.total} has been raised.{pay}"
        self._approval = _auto_estimate(ticket, self.request.user, services, lines)
        email_text = f"Repair ticket {ticket.code} acknowledged -- {device}, drop-off at {ticket.stock_point.name}.{pay}"
        Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=wa_text)
        Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=email_text)
        log_whatsapp(ticket.party, wa_text)
        send_whatsapp(ticket.party.phone, wa_text)
        send_email(ticket.party.email, f"Repair ticket {ticket.code} acknowledged", email_text)
        if self._approval:
            self._approval["whatsapp_delivery"] = send_approval_link_whatsapp(ticket, self._approval["url"], self.request.user)
        # Task 2: internal staff alert, separate from the customer sends
        # above -- who actually gets pinged is configured on Settings >
        # Staff alerts, not hardcoded here.
        notify_staff(
            "repair_ticket_created",
            f"New repair ticket {ticket.code}",
            f"{ticket.party.name} dropped off a {device} for repair -- ticket {ticket.code} at {ticket.stock_point.name}.",
        )

    def _fresh(self, ticket):
        """
        Re-fetch through the full queryset (with its select_related /
        prefetch_related) before serializing a response. Needed because
        DRF's get_object() caches related objects at fetch time;
        creating new related rows afterward in the same request does
        NOT invalidate that cache on the already-fetched instance, so
        serializing it directly would silently return stale data.
        """
        return self.get_queryset().get(pk=ticket.pk)

    def serialized_ticket(self, ticket_id):
        return RepairTicketSerializer(self.get_queryset().get(pk=ticket_id)).data

    @action(detail=True, methods=["post"], url_path="finalize-estimate")
    def finalize_estimate(self, request, pk=None):
        payload = FinalizeEstimateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = self.get_object()
        finalize_estimate(ticket, request.user, payload.validated_data["lines"], payload.validated_data.get("terms", ""))
        return Response(self.serialized_ticket(ticket.pk))

    @action(detail=True, methods=["post"], url_path="approval-link")
    def approval_link(self, request, pk=None):
        ticket = self.get_object()
        approval, approval_url, whatsapp_url = issue_approval_link(ticket, request.user)
        return Response({
            "ticket": self.serialized_ticket(ticket.pk),
            "approval_url": approval_url,
            "whatsapp_url": whatsapp_url,
            "expires_at": approval.expires_at,
            "whatsapp_provider": whatsapp_provider(),
            "send_path": f"/tickets/{ticket.pk}/approval-link/send-whatsapp/",
        })

    @action(detail=True, methods=["post"], url_path="approval-link/send-whatsapp")
    def approval_link_send_whatsapp(self, request, pk=None):
        """Send the link staff just generated through the WhatsApp provider.
        The response says what happened: "sent" only when Meta accepted it."""
        delivery = send_approval_link_whatsapp(self.get_object(), request.data.get("approval_url"), request.user)
        return Response({"whatsapp_delivery": delivery})

    @action(detail=True, methods=["post"], url_path="approve-on-behalf")
    def approve_on_behalf(self, request, pk=None):
        payload = StaffApprovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = self.get_object()
        approve_on_behalf(ticket, request.user, payload.validated_data["reason"])
        return Response(self.serialized_ticket(ticket.pk))

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        """Repair staff: the estimate no longer fits -- send a revised one to
        the Admin / Super Admin. (Their own revision is applied at once.)"""
        payload = ProposeRevisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = self.get_object()
        revision, applied = propose_revision(ticket, request.user, payload.validated_data["lines"], payload.validated_data["reason"])
        data = {"ticket": self.serialized_ticket(ticket.pk), "applied": applied}
        if applied:
            approval = _issue_link_payload(ticket, request.user)
            data["approval"] = approval
            data["ticket"] = self.serialized_ticket(ticket.pk)
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def diagnose(self, request, pk=None):
        """Repair staff: "Diagnosis done" -- the estimate holds, or send a revised one."""
        payload = DiagnoseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = self.get_object()
        if ticket.assigned_to_id != request.user.id:
            raise PermissionDenied("Only the repair staff member this job is assigned to reports the diagnosis.")
        data = payload.validated_data
        _, revision, applied = report_diagnosis(ticket, request.user, data["note"], data["estimate_ok"], data.get("lines"))
        out = {"ticket": self.serialized_ticket(ticket.pk), "applied": applied}
        if applied:
            out["approval"] = _issue_link_payload(ticket, request.user)
            out["ticket"] = self.serialized_ticket(ticket.pk)
        return Response(out, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="decide-revision")
    def decide_revision(self, request, pk=None):
        """Admin / Super Admin: accept (-> new estimate + client link) or
        decline the pending revision."""
        payload = DecideRevisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = self.get_object()
        revision = ticket.pending_revision
        if not revision:
            raise ValidationError({"detail": "There is no revision waiting for review."})
        data = {}
        if payload.validated_data["decision"] == "accept":
            accept_revision(revision, request.user, payload.validated_data.get("note", ""))
            data["approval"] = _issue_link_payload(ticket, request.user)
        else:
            decline_revision(revision, request.user, payload.validated_data.get("note", ""))
        data["ticket"] = self.serialized_ticket(ticket.pk)
        return Response(data)

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        ticket = self.get_object()
        stage = ticket.next_stage()
        if not stage:
            return Response({"detail": "Ticket is already at its final stage."}, status=400)
        if stage == RepairTicket.DELIVERED:
            return Response({"detail": "Raise the invoice instead -- the ticket is marked Delivered automatically once it's paid."}, status=400)
        if ticket.unpaid_invoice:
            return Response({"detail": f"Invoice {ticket.unpaid_invoice.code} is awaiting payment -- collect it in Sales & Invoices first."}, status=400)
        out_of_order = _order_gate(ticket, stage)
        if out_of_order:
            return out_of_order
        if stage == RepairTicket.IN_PROGRESS and ticket.unpaid_advance:
            adv = ticket.unpaid_advance
            return Response({"detail": f"Advance invoice {adv.code} (Rs {adv.total}) is awaiting payment -- collect it in Sales & Invoices, or cancel it there to start without an advance."}, status=400)
        if stage == RepairTicket.IN_PROGRESS and not ticket.has_repair_approval:
            return Response({"detail": "Final customer, Admin, or Super Admin approval is required before work starts."}, status=400)
        blocked = _start_gate(ticket, stage, request)
        if blocked:
            return blocked
        hold = ticket.on_hold_reason
        if hold and stage == RepairTicket.READY:
            return Response({"detail": f"{hold}. The job can't be finished until it's resolved."}, status=400)
        _move(ticket, stage, request.user)
        text = (
            f"Your {ticket.brand} {ticket.model_name} is ready! Please collect it from {ticket.stock_point.name}."
            if stage == RepairTicket.READY
            else f"Update on {ticket.code}: now {stage.lower()}."
        )
        Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=text)
        Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=text)
        _notify_party(ticket.party, f"Update on {ticket.code}", text)
        return Response(RepairTicketSerializer(self._fresh(ticket)).data)

    @action(detail=True, methods=["post"], url_path="set-stage")
    def set_stage(self, request, pk=None):
        """
        Explicit target-stage move -- what the Kanban board's drag-and-
        drop uses, since a card can be dropped on any column, not just
        the next one in sequence. The existing advance() action (always
        "move to the next stage") stays untouched for the detail modal's
        button; this is additive, not a replacement.
        """
        ticket = self.get_object()
        target = request.data.get("status")

        if target not in RepairTicket.STAGES:
            return Response({"detail": f"'{target}' is not a valid stage."}, status=400)
        if target == RepairTicket.DELIVERED:
            return Response(
                {"detail": "Delivered is set automatically once the ticket's invoice is paid in Sales & Invoices."},
                status=400,
            )
        if ticket.unpaid_invoice:
            return Response({"detail": f"Invoice {ticket.unpaid_invoice.code} is awaiting payment -- collect it in Sales & Invoices first."}, status=400)
        if ticket.status == RepairTicket.DELIVERED:
            return Response({"detail": "This ticket has been delivered. Reopen it to make further changes."}, status=400)
        if target == ticket.status:
            return Response(RepairTicketSerializer(self._fresh(ticket)).data)

        out_of_order = _order_gate(ticket, target)
        if out_of_order:
            return out_of_order
        if target == RepairTicket.IN_PROGRESS and ticket.unpaid_advance:
            adv = ticket.unpaid_advance
            return Response({"detail": f"Advance invoice {adv.code} (Rs {adv.total}) is awaiting payment -- collect it in Sales & Invoices, or cancel it there to start without an advance."}, status=400)
        if target == RepairTicket.IN_PROGRESS and not ticket.has_repair_approval:
            return Response({"detail": "Finalize the repair estimate and record customer, Admin, or Super Admin approval before work starts."}, status=400)

        current_idx = RepairTicket.STAGES.index(ticket.status)
        target_idx = RepairTicket.STAGES.index(target)
        is_forward = target_idx > current_idx

        blocked = _start_gate(ticket, target, request)
        if blocked:
            return blocked
        hold = ticket.on_hold_reason
        if hold and target == RepairTicket.READY:
            return Response({"detail": f"{hold}. The job can't be finished until it's resolved."}, status=400)
        _move(ticket, target, request.user)

        if is_forward:
            text = (
                f"Your {ticket.brand} {ticket.model_name} is ready! Please collect it from {ticket.stock_point.name}."
                if target == RepairTicket.READY
                else f"Update on {ticket.code}: now {target.lower()}."
            )
            Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=text)
            Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=text)
            _notify_party(ticket.party, f"Update on {ticket.code}", text)
        # backward move -- an internal correction, no customer notification
        # (see design note: Notification is customer-facing contact history)

        return Response(RepairTicketSerializer(self._fresh(ticket)).data)

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        """
        Raise the job's invoice in Sales & Invoices -- an active reopen gets
        its own follow-up invoice, otherwise the original job is billed.
        The ticket stays "Ready for pickup" until that invoice is paid
        there; payment marks it Delivered (repairs.billing). A
        zero-balance bill (warranty work, fully covered by the advance)
        needs no payment, so the ticket is delivered straight away.
        """
        ticket = self.get_object()
        if ticket.unpaid_invoice:
            return Response({"detail": f"Invoice {ticket.unpaid_invoice.code} is already raised and awaiting payment."}, status=400)
        if ticket.status != RepairTicket.READY:
            return Response({"detail": "Move the ticket to Ready for pickup before raising its invoice."}, status=400)
        active_reopen = ticket.active_reopen

        if active_reopen:
            lines = [
                {
                    "description": item.service.label + (" (covered under warranty)" if item.covered_by_warranty else ""),
                    "qty": 1, "price": item.charge,
                }
                for item in active_reopen.items.select_related("service")
            ]
            what = f"follow-up visit on {ticket.code}"
        else:
            if ticket.original_invoice:
                reconcile_delivery(ticket)
                return Response({"detail": "Already invoiced." if ticket.status != RepairTicket.DELIVERED else "Already invoiced and paid -- the ticket is now marked Delivered."}, status=400)
            if not ticket.has_repair_approval:
                return Response({"detail": "A final customer, Admin, or Super Admin approval is required before settlement."}, status=400)
            estimate = ticket.current_estimate
            if estimate:
                # a line with our parts cost entered counts as goods in the profit report; the rest is labour
                lines = [{"description": line.description, "qty": line.quantity, "price": line.unit_price,
                          "item_kind": "part" if line.unit_cost else "service", "unit_cost": line.unit_cost or None}
                         for line in estimate.lines.all()]
            else:
                lines = [{"description": svc.label, "qty": 1, "price": svc.charge} for svc in ticket.services.all()]
            unpaid_advance = ticket.unpaid_advance
            if unpaid_advance:
                # never paid -- the final bill asks for the full amount instead
                cancel_invoice(unpaid_advance, request.user, "Advance not paid -- the full amount is on the final repair bill.")
            ticket.refresh_from_db(fields=["advance_paid"])
            if ticket.advance_paid:
                lines.append({"description": "Less: advance received", "qty": 1, "price": -ticket.advance_paid})
            what = f"repair {ticket.code}"

        amount = sum(line["qty"] * line["price"] for line in lines)
        today = timezone.localdate()
        payment = (
            {"status": Invoice.PAID, "pay_method": "No charge", "paid_on": today,
             "payment_reference": "Nothing due (warranty / advance covered it)"}
            if amount <= 0 else {"status": Invoice.LINK_SENT}
        )
        with transaction.atomic():
            invoice = create_invoice(
                source=Invoice.REPAIR, repair_ticket=ticket, repair_reopen=active_reopen,
                party=ticket.party, stock_point=ticket.stock_point, date=today, lines=lines, **payment,
            )
            if amount <= 0:
                ticket.status = RepairTicket.DELIVERED
                ticket.save(update_fields=["status"])

        pay = pay_note(invoice, request.user) if amount > 0 else ""
        if amount <= 0:
            wa_text = f"Thank you! Your {what} is complete -- invoice {invoice.code}, nothing to pay."
        else:
            wa_text = f"Your {what} is ready. Invoice {invoice.code} for Rs {amount} has been raised -- please pay to collect your device.{pay}"
        email_text = f"Invoice {invoice.code} raised at {ticket.stock_point.name} for {what}: Rs {max(amount, 0)}.{pay}"
        Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=wa_text)
        Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=email_text)
        log_whatsapp(ticket.party, wa_text)
        send_whatsapp(ticket.party.phone, wa_text)
        send_email(ticket.party.email, f"Invoice {invoice.code}", email_text)
        return Response(RepairTicketSerializer(self._fresh(ticket)).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        """
        The device came back. Reopens the SAME ticket (status returns
        to In progress) rather than creating a new one, per the chosen
        policy. Every requested service is checked against what this
        ticket was ORIGINALLY serviced for:
          - same service + an active repair warranty on this ticket
            -> suggested charge is 0 (staff can override per item)
          - a service that wasn't part of the original job (a new,
            unrelated problem, or a part that wasn't replaced before)
            -> full price, warranty or not -- warranty only covers
            what was actually fixed the first time.
        """
        ticket = self.get_object()
        if ticket.status != RepairTicket.DELIVERED:
            return Response({"detail": "Only a delivered ticket can be reopened."}, status=400)
        if ticket.active_reopen:
            return Response({"detail": "This ticket already has an open follow-up visit."}, status=400)

        issue = (request.data.get("issue") or "").strip()
        items = request.data.get("items") or []
        if not issue:
            return Response({"detail": "Describe the problem the customer is reporting."}, status=400)
        if not items:
            return Response({"detail": "Select at least one service for this visit."}, status=400)

        from warranty.models import Warranty
        active_warranty = (
            Warranty.objects.filter(repair_ticket=ticket, section=Warranty.REPAIR, end_date__gte=date.today())
            .order_by("-end_date").first()
        )
        original_service_ids = set(ticket.services.values_list("id", flat=True))

        reopen_obj = RepairReopen.objects.create(ticket=ticket, issue=issue)
        for item in items:
            service_id = item.get("service")
            service = Service.objects.filter(pk=service_id).first()
            if not service:
                reopen_obj.delete()
                return Response({"detail": f"No such service: {service_id}."}, status=400)
            is_recurrence = service.id in original_service_ids
            covered = bool(active_warranty) and is_recurrence
            override = item.get("override_charge")
            if override is not None:
                try:
                    charge = max(0, int(override))
                except (TypeError, ValueError):
                    charge = 0 if covered else service.charge
            else:
                charge = 0 if covered else service.charge
            RepairReopenItem.objects.create(reopen=reopen_obj, service=service, charge=charge, covered_by_warranty=covered)

        ticket.status = RepairTicket.IN_PROGRESS
        ticket.save(update_fields=["status"])

        if active_warranty and any(i.covered_by_warranty for i in reopen_obj.items.all()):
            note = f"Your {ticket.brand} {ticket.model_name} is back in for a warranty-covered follow-up on {ticket.code}. No charge for the covered work."
        else:
            note = f"Your {ticket.brand} {ticket.model_name} is back in for further service on {ticket.code}."
        Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=note)
        Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=note)
        _notify_party(ticket.party, f"{ticket.code} reopened for follow-up", note)

        return Response(RepairTicketSerializer(self._fresh(ticket)).data, status=201)


class RepairApprovalPublicView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "repair_approval"

    def get(self, request, token):
        return _private_response(PublicRepairApprovalSerializer(get_public_approval(token)).data)

    def post(self, request, token):
        payload = PublicApprovalDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approval = customer_decide(
            token,
            payload.validated_data["decision"],
            payload.validated_data.get("consent", False),
            payload.validated_data.get("reason", ""),
        )
        return _private_response(PublicRepairApprovalSerializer(approval).data)


class RepairOrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        RepairOrder.objects.select_related("party")
        .prefetch_related(
            "approvals",
            "tickets__party",
            "tickets__stock_point",
            "tickets__services__part",
            "tickets__notifications",
            "tickets__invoices",
            "tickets__reopens__items",
            "tickets__reopens__invoice",
            "tickets__estimates__lines",
            "tickets__estimates__approvals",
            "tickets__events",
        )
        .all()
    )
    serializer_class = RepairOrderSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "repairs.view",
        "retrieve": "repairs.view",
        "create": "repairs.book",
        "approval_link": "repairs.approve",
        "approval_link_send_whatsapp": "repairs.approve",
        "approve_on_behalf": "repairs.approve",
    }

    def get_queryset(self):
        # An order belongs to a store when every one of its tickets does
        # (orders are created for a single drop-off shop); one with any
        # ticket elsewhere stays Owner-only rather than leaking that ticket.
        scope = StoreScope(self.request.user)
        qs = super().get_queryset()
        if scope.all:
            return qs
        if scope.store_id is None:
            return qs.none()
        elsewhere = RepairTicket.objects.exclude(stock_point_id=scope.store_id)
        return (
            qs.filter(tickets__stock_point_id=scope.store_id).exclude(tickets__in=elsewhere).distinct()
            .prefetch_related(part_stock_prefetch(scope, "tickets__services__part__stock"))
        )

    def get_serializer_class(self):
        return CreateRepairOrderSerializer if self.action == "create" else RepairOrderSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        StoreScope(request.user).require(request.data.get("stock_point"), "repair orders")
        payload = CreateRepairOrderSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        devices = data.pop("devices")
        order = RepairOrder.objects.create(
            party=data["party"],
            created_by=request.user,
        )
        order.code = f"RPR-ORD-{order.pk:06d}"
        order.save(update_fields=["code"])

        auto = []
        for device in devices:
            services = device.pop("services", [])
            lines = device.pop("estimate_lines", [])
            typed_advance = device.pop("advance_amount", None)
            ticket = RepairTicket.objects.create(
                order=order,
                code=f"RPR-TEMP-{order.pk}-{len(order.tickets.all()) + 1}",
                party=order.party,
                brand=device["brand"],
                model_name=device["model_name"],
                serial=device["serial"],
                stock_point=data["stock_point"],
                issue=device["issue"],
                received=data["received"],
                expected=data.get("expected"),
                payment=data["payment"],
            )
            ticket.code = f"RPR-{1044 + ticket.pk}"
            ticket.save(update_fields=["code"])
            ticket.services.set(services)
            built = _booking_lines(services, lines)
            if typed_advance is not None and built and typed_advance > sum(l["quantity"] * l["unit_price"] for l in built if l["unit_price"] is not None):
                raise ValidationError({"advance_amount": f"The advance for {ticket.brand} {ticket.model_name} can't be more than its estimate."})
            device_label = f"{ticket.brand} {ticket.model_name}"
            wa_text = f"Ticket {ticket.code} created for your {device_label} under order {order.code}."
            pay = ""
            if ticket.payment == RepairTicket.ADVANCE:
                advance_invoice = raise_advance_invoice(ticket, _booking_advance(ticket.payment, typed_advance, services))
                if advance_invoice:
                    pay = pay_note(advance_invoice, request.user)
                    wa_text += f" Advance invoice {advance_invoice.code} for Rs {advance_invoice.total} has been raised.{pay}"
            email_text = f"Repair ticket {ticket.code} acknowledged under {order.code} -- {device_label}.{pay}"
            Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=wa_text)
            Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=email_text)
            log_whatsapp(ticket.party, wa_text)
            send_whatsapp(ticket.party.phone, wa_text)
            send_email(ticket.party.email, f"Repair ticket {ticket.code} acknowledged", email_text)
            if built and request.user.has_perm_code("repairs.approve"):
                finalize_estimate(ticket, request.user, built)
                auto.append(ticket)
        fresh = self.get_queryset().get(pk=order.pk)
        body = RepairOrderSerializer(fresh).data
        if auto and len(auto) == order.tickets.count():
            if len(auto) >= 2:
                approval, url = issue_order_approval_link(order, request.user)
                link = _order_link_payload(order, approval, url)
            else:
                link = _issue_link_payload(auto[0], request.user)
            body = {**RepairOrderSerializer(self.get_queryset().get(pk=order.pk)).data, "approval": link}
        return Response(body, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="approval-link")
    def approval_link(self, request, pk=None):
        order = self.get_object()
        approval, approval_url = issue_order_approval_link(order, request.user)
        link = _order_link_payload(order, approval, approval_url)
        return Response({
            "order": RepairOrderSerializer(self.get_queryset().get(pk=approval.order_id)).data,
            "approval_url": approval_url,
            "whatsapp_url": link["whatsapp_url"],
            "expires_at": approval.expires_at,
            "whatsapp_provider": link["whatsapp_provider"],
            "send_path": link["send_path"],
        })

    @action(detail=True, methods=["post"], url_path="approval-link/send-whatsapp")
    def approval_link_send_whatsapp(self, request, pk=None):
        delivery = send_order_approval_link_whatsapp(self.get_object(), request.data.get("approval_url"), request.user)
        return Response({"whatsapp_delivery": delivery})

    @action(detail=True, methods=["post"], url_path="approve-on-behalf")
    def approve_on_behalf(self, request, pk=None):
        payload = StaffApprovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approval = approve_order_on_behalf(
            self.get_object(), request.user, payload.validated_data["reason"]
        )
        return Response(RepairOrderSerializer(self.get_queryset().get(pk=approval.order_id)).data)


class RepairOrderApprovalPublicView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "repair_approval"

    def get(self, request, token):
        return _private_response(
            PublicRepairOrderApprovalSerializer(get_public_order_approval(token)).data
        )

    def post(self, request, token):
        payload = PublicApprovalDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        approval = customer_decide_order(
            token,
            payload.validated_data["decision"],
            payload.validated_data.get("consent", False),
            payload.validated_data.get("reason", ""),
        )
        return _private_response(PublicRepairOrderApprovalSerializer(approval).data)

