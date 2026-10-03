import json
from datetime import date

from django.conf import settings
from django.db import transaction
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasPerm
from crmbook_backend.notify import notify_staff
from parties.models import Message

from . import payments
from .models import PAYMENT_METHODS, Invoice, PaymentLink
from .services import on_invoice_paid
from .serializers import InvoiceSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.select_related(
        "party", "stock_point", "settled_by", "repair_ticket", "rental",
    ).prefetch_related("items__variant__product", "payment_links__sent_by").all()
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perms = {
        "list": "invoices.view", "retrieve": "invoices.view",
        "create": "invoices.create", "update": "invoices.create",
        "partial_update": "invoices.create", "destroy": "invoices.create",
        "settle": "invoices.settle",
        "print_data": "invoices.view",
        "upi_check": "payments.send_link",
        "send_upi_link": "payments.send_link",
        "refresh_payment": "payments.send_link",
        "simulate_payment": "invoices.settle",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status")
        party = self.request.query_params.get("party")
        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)
        if status:
            qs = qs.filter(status=status)
        if party:
            qs = qs.filter(party_id=party)
        return qs

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        """
        Record a payment received outside any gateway: how it was paid,
        the reference to match against the bank/UPI statement, and when.
        Body: {"pay_method": "UPI", "payment_reference": "UTR 4123...",
        "paid_on": "2026-10-03"} -- paid_on defaults to today. A reference
        is required for every method except cash.
        """
        invoice = self.get_object()
        if invoice.status == Invoice.PAID:
            return Response({"detail": "This invoice is already marked paid."}, status=400)
        method = (request.data.get("pay_method") or "").strip()
        reference = (request.data.get("payment_reference") or "").strip()
        if method not in PAYMENT_METHODS:
            return Response({"detail": f"pay_method must be one of: {', '.join(PAYMENT_METHODS)}."}, status=400)
        if method != "Cash" and not reference:
            return Response({"detail": "Enter the payment reference (UPI/UTR, cheque or card transaction number)."}, status=400)
        if len(reference) > 80:
            return Response({"detail": "payment_reference must be 80 characters or fewer."}, status=400)
        try:
            paid_on = date.fromisoformat(request.data["paid_on"]) if request.data.get("paid_on") else date.today()
        except (TypeError, ValueError):
            return Response({"detail": "paid_on must be a date (YYYY-MM-DD)."}, status=400)
        if paid_on > date.today():
            return Response({"detail": "paid_on can't be in the future."}, status=400)

        invoice.status = Invoice.PAID
        invoice.pay_method = method
        invoice.payment_reference = reference
        invoice.paid_on = paid_on
        invoice.settled_by = request.user
        invoice.save(update_fields=["status", "pay_method", "payment_reference", "paid_on", "settled_by"])
        on_invoice_paid(invoice)
        # Task 2 wiring: "any payment done" -- who actually gets pinged is
        # configured on Settings > Staff alerts, not hardcoded here.
        notify_staff(
            "payment_received",
            f"Invoice {invoice.code} settled",
            f"Invoice {invoice.code} for {invoice.party.name} was marked paid -- ₹{invoice.total}.",
        )
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["get"], url_path="print-data")
    def print_data(self, request, pk=None):
        """Everything the printable invoice needs in one call: seller and
        branch details, buyer details, and line items with HSN."""
        invoice = self.get_object()
        sp, party = invoice.stock_point, invoice.party
        items = []
        for n, item in enumerate(invoice.items.all(), start=1):
            variant = item.variant
            items.append({
                "n": n,
                "description": item.description or variant.product.display_name,
                "spec": variant.spec if variant else "",
                "code": variant.code if variant else "",
                "hsn": variant.product.hsn if variant else "",
                "qty": item.qty,
                "rate": item.price,
                "amount": item.qty * item.price,
            })
        return Response({
            "invoice": InvoiceSerializer(invoice).data,
            "reference": InvoiceSerializer(invoice).data["reference"],
            "seller": {
                "name": settings.BUSINESS_NAME,
                "branch": sp.name,
                "address": sp.address,
                "phone": sp.phone or settings.BUSINESS_PHONE,
                "email": settings.BUSINESS_EMAIL,
                "gstin": sp.gstin or settings.BUSINESS_GSTIN,
            },
            "buyer": {
                "name": party.name, "phone": party.phone, "email": party.email,
                "gstin": party.gstin, "city": party.city,
            },
            "items": items,
            "total_qty": sum(i["qty"] for i in items),
            "total": sum(i["amount"] for i in items),
        })

    # -------------------------------------------------------------- #
    #  UPI payment links -- see sales/payments.py for the whole flow.
    # -------------------------------------------------------------- #

    def _refuse_repair_staff(self, request):
        """Payment links are never sent by Repair Staff, even if a role
        edit ever hands that role payments.send_link by mistake."""
        role = getattr(request.user, "role", None)
        if not request.user.is_superuser and role and role.slug == "repair_staff":
            return Response({"detail": "Repair staff can't send payment links."}, status=403)
        return None

    def _phone_from(self, request, invoice):
        raw = request.data.get("phone") or invoice.party.phone
        phone = payments.normalize_mobile(raw)
        if not phone:
            return None, Response({"detail": f"\"{raw or ''}\" isn't a valid 10-digit Indian mobile number."}, status=400)
        return phone, None

    @action(detail=True, methods=["post"], url_path="upi-check")
    def upi_check(self, request, pk=None):
        """Is this number (default: the customer's number on file) on UPI?"""
        refused = self._refuse_repair_staff(request)
        if refused:
            return refused
        invoice = self.get_object()
        phone, error = self._phone_from(request, invoice)
        if error:
            return error
        result = payments.check_upi_linked(phone)
        return Response({
            "phone": phone,
            "is_customer_number": phone == payments.normalize_mobile(invoice.party.phone),
            **result,
        })

    @action(detail=True, methods=["post"], url_path="send-upi-link")
    def send_upi_link(self, request, pk=None):
        """
        Body: {"phone": "98xxxxxxxx", "staff_confirmed_upi": false}.
        The number is re-checked here (never trust the earlier check
        alone): a number with no UPI is refused; if the check can't run,
        the sender must confirm they've verified it with the customer.
        """
        refused = self._refuse_repair_staff(request)
        if refused:
            return refused
        invoice = self.get_object()
        if invoice.status == Invoice.PAID:
            return Response({"detail": "This invoice is already paid."}, status=400)
        if invoice.total <= 0:
            return Response({"detail": "This invoice has no amount to collect."}, status=400)
        phone, error = self._phone_from(request, invoice)
        if error:
            return error

        check = payments.check_upi_linked(phone)
        if check["status"] == payments.NOT_LINKED:
            return Response({"detail": "This number isn't linked to UPI -- ask the customer for a number that has UPI.", "upi_status": check["status"]}, status=400)
        if check["status"] == payments.UNKNOWN and request.data.get("staff_confirmed_upi") is not True:
            return Response({"detail": "Couldn't check this number automatically -- confirm with the customer that it has UPI, then tick the confirmation.", "upi_status": check["status"]}, status=400)
        upi_check = PaymentLink.UPI_VERIFIED if check["status"] == payments.LINKED else PaymentLink.UPI_STAFF_CONFIRMED

        sender = request.user.get_full_name() or request.user.username
        description = (
            f"Hi {invoice.party.name}, {sender} from {settings.BUSINESS_NAME} has sent you a UPI payment link "
            f"for invoice {invoice.code} of Rs {invoice.total}."
        )
        try:
            created = payments.create_upi_link(invoice, phone, sender, description)
        except payments.PaymentProviderError as e:
            return Response({"detail": str(e)}, status=502)

        with transaction.atomic():
            # a fresh link supersedes any earlier unpaid one
            invoice.payment_links.filter(status=PaymentLink.SENT).update(status=PaymentLink.CANCELLED)
            link = PaymentLink.objects.create(
                invoice=invoice, phone=phone, upi_check=upi_check, amount=invoice.total,
                provider=payments.payment_provider(), provider_link_id=created["provider_link_id"],
                url=created["url"], sent_by=request.user,
            )
            if invoice.status != Invoice.OVERDUE:
                invoice.status = Invoice.LINK_SENT
                invoice.save(update_fields=["status"])
            Message.objects.create(
                party=invoice.party, channel=Message.SMS, direction=Message.OUT,
                body=f"{description} Pay here: {created['url']} (sent to ******{phone[-4:]})",
            )
        invoice.refresh_from_db()
        return Response(InvoiceSerializer(invoice).data, status=201)

    @action(detail=True, methods=["post"], url_path="refresh-payment")
    def refresh_payment(self, request, pk=None):
        """Ask the payment provider whether the open link has been paid --
        for when the webhook can't reach this server (e.g. running locally)."""
        refused = self._refuse_repair_staff(request)
        if refused:
            return refused
        invoice = self.get_object()
        link = invoice.payment_links.filter(status=PaymentLink.SENT).first()
        if not link:
            return Response({"detail": "No open payment link for this invoice."}, status=400)
        try:
            result = payments.fetch_link_payment(link)
        except payments.PaymentProviderError as e:
            return Response({"detail": str(e)}, status=502)
        if result["paid"]:
            payments.mark_link_paid(link, payment_id=result["payment_id"], rrn=result["rrn"])
        invoice.refresh_from_db()
        return Response({"paid": result["paid"], "invoice": InvoiceSerializer(invoice).data})

    @action(detail=True, methods=["post"], url_path="simulate-payment")
    def simulate_payment(self, request, pk=None):
        """Sandbox only: pretend the customer paid the open link, to try the
        paid path without real money."""
        invoice = self.get_object()
        link = invoice.payment_links.filter(status=PaymentLink.SENT, provider="sandbox").first()
        if not link:
            return Response({"detail": "No open sandbox payment link for this invoice."}, status=400)
        payments.mark_link_paid(link, payment_id=f"sandbox_pay_{link.pk}", rrn="000000000000")
        invoice.refresh_from_db()
        return Response(InvoiceSerializer(invoice).data)


class RazorpayWebhookView(APIView):
    """
    Razorpay calls this when a payment link is paid (subscribe to the
    "payment_link.paid" event in the Razorpay dashboard). Authenticated
    only by the HMAC signature over the raw body, using
    RAZORPAY_WEBHOOK_SECRET -- anything unsigned or mis-signed is refused.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw = request.body
        if not payments.verify_razorpay_signature(raw, request.headers.get("X-Razorpay-Signature", "")):
            return Response({"detail": "invalid signature"}, status=400)
        try:
            event = json.loads(raw)
        except ValueError:
            return Response({"detail": "invalid body"}, status=400)
        if event.get("event") != "payment_link.paid":
            return Response({"status": "ignored"})
        payload = event.get("payload", {})
        link_id = payload.get("payment_link", {}).get("entity", {}).get("id")
        payment = payload.get("payment", {}).get("entity", {})
        link = PaymentLink.objects.select_related("invoice").filter(provider="razorpay", provider_link_id=link_id).first()
        if not link:
            return Response({"status": "unknown link"})
        payments.mark_link_paid(link, payment_id=payment.get("id"), rrn=(payment.get("acquirer_data") or {}).get("rrn"))
        return Response({"status": "ok"})
