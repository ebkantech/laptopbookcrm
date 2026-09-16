from datetime import date
import json
from uuid import uuid4

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from catalog.models import Service
from .models import Notification, RepairInvoice, RepairOrder, RepairReopen, RepairReopenItem, RepairTicket, RepairTicketEvent
from .serializers import (
    CreateRepairOrderSerializer,
    FinalizeEstimateSerializer,
    PublicApprovalDecisionSerializer,
    PublicRepairApprovalSerializer,
    PublicRepairOrderApprovalSerializer,
    RepairInvoiceListSerializer,
    RepairOrderSerializer,
    RepairTicketSerializer,
    StaffApprovalSerializer,
)
from .services import (
    approve_on_behalf,
    approve_order_on_behalf,
    customer_decide,
    customer_decide_order,
    finalize_estimate,
    get_public_approval,
    get_public_order_approval,
    issue_approval_link,
    issue_order_approval_link,
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


class RepairTicketViewSet(viewsets.ModelViewSet):
    queryset = (
        RepairTicket.objects
        .select_related("party", "stock_point", "order")
        .prefetch_related(
            "services__part", "notifications", "invoices", "reopens__items", "reopens__invoice",
            "estimates__lines", "estimates__approvals", "events",
            "order__tickets__estimates__lines", "order__tickets__estimates__approvals",
        )
        .all()
    )
    serializer_class = RepairTicketSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "repairs.view", "retrieve": "repairs.view",
        "create": "repairs.manage", "update": "repairs.manage",
        "partial_update": "repairs.manage", "destroy": "repairs.manage",
        "advance": "repairs.manage", "settle": "repairs.manage",
        "set_stage": "repairs.manage", "reopen": "repairs.manage",
        "finalize_estimate": "repairs.manage", "approval_link": "repairs.manage",
        "approve_on_behalf": "repairs.approve",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

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

    @transaction.atomic
    def perform_create(self, serializer):
        services = serializer.validated_data.get("services", [])
        ticket = serializer.save(code=f"TMP-{uuid4().hex[:16]}", status=RepairTicket.RECEIVED)
        ticket.code = f"RPR-{1044 + ticket.pk}"
        ticket.save(update_fields=["code"])
        device = f"{ticket.brand} {ticket.model_name}"
        Notification.objects.create(
            ticket=ticket, channel=Notification.WHATSAPP,
            text=f"Ticket {ticket.code} created for your {device}. We'll keep you posted.",
        )
        Notification.objects.create(
            ticket=ticket, channel=Notification.EMAIL,
            text=f"Repair ticket {ticket.code} acknowledged -- {device}, drop-off at {ticket.stock_point.name}.",
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
        })

    @action(detail=True, methods=["post"], url_path="approve-on-behalf")
    def approve_on_behalf(self, request, pk=None):
        payload = StaffApprovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = self.get_object()
        approve_on_behalf(ticket, request.user, payload.validated_data["reason"])
        return Response(self.serialized_ticket(ticket.pk))

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        ticket = self.get_object()
        stage = ticket.next_stage()
        if not stage:
            return Response({"detail": "Ticket is already at its final stage."}, status=400)
        if stage == RepairTicket.IN_PROGRESS and not ticket.has_repair_approval:
            return Response({"detail": "Final customer, Admin, or Super Admin approval is required before work starts."}, status=400)
        ticket.status = stage
        ticket.save(update_fields=["status"])
        text = (
            f"Your {ticket.brand} {ticket.model_name} is ready! Please collect it from {ticket.stock_point.name}."
            if stage == RepairTicket.READY
            else f"Update on {ticket.code}: now {stage.lower()}."
        )
        Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=text)
        Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=text)
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
                {"detail": "Delivered can only be set by settling the ticket (generates the invoice) -- use the settle action instead."},
                status=400,
            )
        if ticket.status == RepairTicket.DELIVERED:
            return Response({"detail": "This ticket has been delivered. Reopen it to make further changes."}, status=400)
        if target == ticket.status:
            return Response(RepairTicketSerializer(self._fresh(ticket)).data)

        if target == RepairTicket.IN_PROGRESS and not ticket.has_repair_approval:
            return Response({"detail": "Finalize the repair estimate and record customer, Admin, or Super Admin approval before work starts."}, status=400)

        current_idx = RepairTicket.STAGES.index(ticket.status)
        target_idx = RepairTicket.STAGES.index(target)
        is_forward = target_idx > current_idx

        ticket.status = target
        ticket.save(update_fields=["status"])

        if is_forward:
            text = (
                f"Your {ticket.brand} {ticket.model_name} is ready! Please collect it from {ticket.stock_point.name}."
                if target == RepairTicket.READY
                else f"Update on {ticket.code}: now {target.lower()}."
            )
            Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=text)
            Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=text)
        # backward move -- an internal correction, no customer notification
        # (see design note: Notification is customer-facing contact history)

        return Response(RepairTicketSerializer(self._fresh(ticket)).data)

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        """
        Settles whichever is currently open: an active reopen if one
        exists, otherwise the original job. Each gets its own
        RepairInvoice -- settling a reopen never touches or re-charges
        what was already billed on the original delivery.
        """
        ticket = self.get_object()
        active_reopen = ticket.active_reopen

        if active_reopen:
            amount = active_reopen.total
            invoice = RepairInvoice.objects.create(
                ticket=ticket, reopen=active_reopen, code=f"RPR-INV-{ticket.code.split('-')[1]}-R{active_reopen.id}",
                amount=amount, stock_point=ticket.stock_point, status="Paid", date=timezone.now().date(),
            )
            wa_text = (
                f"Thank you! {invoice.code} settled -- {'no charge, covered under warranty.' if amount == 0 else 'amount collected on delivery.'}"
            )
            email_text = f"Invoice {invoice.code} generated at {ticket.stock_point.name} and marked paid."
        else:
            if ticket.original_invoice:
                return Response({"detail": "Already settled."}, status=400)
            if not ticket.has_repair_approval:
                return Response({"detail": "A final customer, Admin, or Super Admin approval is required before settlement."}, status=400)
            amount = ticket.total - ticket.advance_paid
            invoice = RepairInvoice.objects.create(
                ticket=ticket, reopen=None, code=f"RPR-INV-{ticket.code.split('-')[1]}", amount=amount,
                stock_point=ticket.stock_point, status="Paid", date=timezone.now().date(),
            )
            wa_text = f"Thank you! {invoice.code} settled -- amount collected on delivery."
            email_text = f"Invoice {invoice.code} generated at {ticket.stock_point.name} and marked paid."

        ticket.status = RepairTicket.DELIVERED
        ticket.save(update_fields=["status"])
        Notification.objects.create(ticket=ticket, channel=Notification.WHATSAPP, text=wa_text)
        Notification.objects.create(ticket=ticket, channel=Notification.EMAIL, text=email_text)
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
        "create": "repairs.manage",
        "approval_link": "repairs.manage",
        "approve_on_behalf": "repairs.approve",
    }

    def get_serializer_class(self):
        return CreateRepairOrderSerializer if self.action == "create" else RepairOrderSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
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

        for device in devices:
            services = device.pop("services")
            total = sum(service.charge for service in services)
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
                advance_paid=round(total * 0.25) if data["payment"] == RepairTicket.ADVANCE else 0,
            )
            ticket.code = f"RPR-{1044 + ticket.pk}"
            ticket.save(update_fields=["code"])
            ticket.services.set(services)
            device_label = f"{ticket.brand} {ticket.model_name}"
            Notification.objects.create(
                ticket=ticket,
                channel=Notification.WHATSAPP,
                text=f"Ticket {ticket.code} created for your {device_label} under order {order.code}.",
            )
            Notification.objects.create(
                ticket=ticket,
                channel=Notification.EMAIL,
                text=f"Repair ticket {ticket.code} acknowledged under {order.code} -- {device_label}.",
            )
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(RepairOrderSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="approval-link")
    def approval_link(self, request, pk=None):
        approval, approval_url = issue_order_approval_link(self.get_object(), request.user)
        return Response({
            "order": RepairOrderSerializer(self.get_queryset().get(pk=approval.order_id)).data,
            "approval_url": approval_url,
            "expires_at": approval.expires_at,
        })

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


class RepairInvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Repair bills, listable on their own -- this is what lets the Sales
    & Invoices screen (and the Dashboard's revenue figure) show repair
    income instead of it being visible only inside the Repairs module.
    """
    queryset = RepairInvoice.objects.select_related("ticket__party", "stock_point").all()
    serializer_class = RepairInvoiceListSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "repairs.view"

    def get_queryset(self):
        qs = super().get_queryset()
        status_ = self.request.query_params.get("status")
        if status_:
            qs = qs.filter(status=status_)
        return qs.order_by("-date", "-id")
