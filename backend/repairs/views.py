from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasPerm
from catalog.models import Service
from .models import Notification, RepairInvoice, RepairReopen, RepairReopenItem, RepairTicket
from .serializers import RepairInvoiceListSerializer, RepairTicketSerializer


class RepairTicketViewSet(viewsets.ModelViewSet):
    queryset = (
        RepairTicket.objects
        .select_related("party", "stock_point")
        .prefetch_related("services__part", "notifications", "invoices", "reopens__items", "reopens__invoice")
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
    }

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        services = serializer.validated_data.get("services", [])
        last = RepairTicket.objects.order_by("-id").first()
        next_num = 1044 + (last.id if last else 0) + 1
        ticket = serializer.save(code=f"RPR-{next_num}", status=RepairTicket.RECEIVED)
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

    @action(detail=True, methods=["post"])
    def advance(self, request, pk=None):
        ticket = self.get_object()
        stage = ticket.next_stage()
        if not stage:
            return Response({"detail": "Ticket is already at its final stage."}, status=400)
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
