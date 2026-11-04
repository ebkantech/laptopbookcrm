from collections import Counter

from django.db import transaction
from django.db.models import F, Q
from rest_framework import serializers

from catalog.models import Stock
from catalog.status import require_active
from .models import Invoice, InvoiceItem, PaymentLink, Refund
from .services import create_invoice


class InvoiceItemSerializer(serializers.ModelSerializer):
    variant_code = serializers.SerializerMethodField()
    # Kept as product_name for existing callers: the line's label, i.e.
    # the product for a sale line or the service/rent description.
    product_name = serializers.CharField(source="label", read_only=True)
    returned_qty = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceItem
        fields = ["id", "variant", "variant_code", "product_name", "description", "qty", "price", "returned_qty"]
        read_only_fields = ["description"]

    def get_returned_qty(self, obj):
        return sum(r.qty for r in obj.refund_items.all()) if obj.pk else 0

    def get_variant_code(self, obj):
        return obj.variant.code if obj.variant_id else None


class PaymentLinkSerializer(serializers.ModelSerializer):
    phone_masked = serializers.SerializerMethodField()
    sent_by_name = serializers.SerializerMethodField()
    upi_check_label = serializers.CharField(source="get_upi_check_display", read_only=True)

    class Meta:
        model = PaymentLink
        fields = [
            "id", "phone_masked", "upi_check", "upi_check_label", "amount", "provider", "url",
            "status", "sent_by_name", "created_at", "paid_at", "provider_payment_id",
        ]

    def get_phone_masked(self, obj):
        return f"******{obj.phone[-4:]}"

    def get_sent_by_name(self, obj):
        return obj.sent_by.get_full_name() or obj.sent_by.username


class RefundSerializer(serializers.ModelSerializer):
    by_name = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()

    class Meta:
        model = Refund
        fields = ["id", "amount", "method", "reference", "reason", "refunded_on", "restocked", "by_name", "created_at", "items"]

    def get_by_name(self, obj):
        return obj.by.get_full_name() or obj.by.username

    def get_items(self, obj):
        return [{"label": ri.invoice_item.label, "qty": ri.qty} for ri in obj.items.all()]


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True)
    party_name = serializers.CharField(source="party.name", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    settled_by_name = serializers.SerializerMethodField()
    payment_links = PaymentLinkSerializer(many=True, read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    reference = serializers.SerializerMethodField()
    refunds = RefundSerializer(many=True, read_only=True)
    refunded_total = serializers.IntegerField(read_only=True)
    net_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "source", "source_label", "reference", "party", "party_name", "stock_point", "stock_point_name",
            "date", "status", "pay_method", "paid_on", "payment_reference", "settled_by_name",
            "recurring_interval", "recurring_next", "repair_ticket", "rental", "lead", "period_start", "period_end",
            "due_date", "cancel_reason", "cancelled_at", "cancelled_by_name",
            "items", "total", "payment_links", "is_advance", "refunds", "refunded_total", "net_total",
        ]
        # Payment details are only ever written by the settle action, so
        # every settlement goes through its validation and audit fields;
        # repair/rental links are only ever set by those modules.
        read_only_fields = [
            "code", "source", "paid_on", "payment_reference", "repair_ticket", "rental", "lead", "period_start", "period_end",
            "cancel_reason", "cancelled_at", "status", "is_advance",
        ]

    def get_reference(self, obj):
        """What this invoice was raised for, in words, e.g. the repair
        ticket or the rental agreement and month."""
        if obj.source == Invoice.REPAIR and obj.repair_ticket_id:
            if obj.is_advance:
                return f"Advance for repair {obj.repair_ticket.code}"
            return f"Repair {obj.repair_ticket.code}" + (" (follow-up visit)" if obj.repair_reopen_id else "")
        if obj.source == Invoice.RENTAL and obj.rental_id:
            label = obj.rental.agreement_code or f"Rental #{obj.rental_id}"
            if obj.period_start and obj.period_end:
                return f"{label} · {obj.period_start:%d %b %Y} – {obj.period_end:%d %b %Y}"
            return label
        if obj.source == Invoice.ONSITE and obj.lead_id:
            kind = "Advance for" if obj.is_advance else "Visit charge for" if obj.items.filter(description__startswith="Visit charge").count() and obj.lead.status == "rejected" else "On-site service"
            return f"{kind} {obj.lead.code}"
        return None

    cancelled_by_name = serializers.SerializerMethodField()

    def get_cancelled_by_name(self, obj):
        return (obj.cancelled_by.get_full_name() or obj.cancelled_by.username) if obj.cancelled_by else None

    def get_settled_by_name(self, obj):
        return (obj.settled_by.get_full_name() or obj.settled_by.username) if obj.settled_by else None

    def validate_stock_point(self, value):
        # a new invoice can't be raised at an inactive shop / channel; an
        # existing invoice keeps its stock point whatever its status
        require_active(value, "invoices", current=self.instance.stock_point_id if self.instance else None)
        return value

    def validate_items(self, items):
        # This endpoint creates product sales only (repair/rental invoices
        # are raised by their own modules): every line is a stock variant.
        if not items:
            raise serializers.ValidationError("An invoice needs at least one item.")
        for item in items:
            if not item.get("variant"):
                raise serializers.ValidationError("Every sale line needs a product variant.")
            if item.get("price", 0) < 0:
                raise serializers.ValidationError("Prices can't be negative.")
            if item.get("qty", 0) < 1:
                raise serializers.ValidationError("Quantity must be at least 1.")
        return items

    @staticmethod
    def _units(lines, stock_point, sign=1):
        """{(stock point, variant): units} for these sale lines -- dicts
        from the request or saved InvoiceItems."""
        units = Counter()
        for line in lines:
            variant, qty = (line["variant"], line["qty"]) if isinstance(line, dict) else (line.variant, line.qty)
            if variant is not None:
                units[(stock_point, variant)] += sign * qty
        return units

    @staticmethod
    def _move_stock(changes):
        """
        Apply a sale's stock changes: {(stock point, variant): units taken
        off the shelf (+) or put back (-)}. Every shelf row involved is
        locked first, in id order so two sales can't deadlock; taking more
        than is there is refused (instead of the database refusing with a
        server error) before anything moves.
        """
        changes = {key: qty for key, qty in changes.items() if qty}
        if not changes:
            return
        lookup = Q()
        for stock_point, variant in changes:
            lookup |= Q(stock_point=stock_point, variant=variant)
        rows = {
            (row.stock_point_id, row.variant_id): row
            for row in Stock.objects.select_for_update().filter(lookup).order_by("pk")
        }
        problems = []
        for (stock_point, variant), qty in changes.items():
            row = rows.get((stock_point.id, variant.id))
            have = row.quantity if row else 0
            if qty > have:
                name = f"{variant.product.display_name} ({variant.spec})"
                problems.append(
                    f"{name}: only {have} in stock at {stock_point.name}" if row
                    else f"{name} isn't stocked at {stock_point.name}"
                )
        if problems:
            raise serializers.ValidationError({"items": problems})
        for (stock_point, variant), qty in changes.items():
            row = rows.get((stock_point.id, variant.id))
            if row:
                Stock.objects.filter(pk=row.pk).update(quantity=F("quantity") - qty)
            else:  # only a put-back gets here: the shelf row was removed since the sale
                Stock.objects.create(variant=variant, stock_point=stock_point, quantity=-qty)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        validated_data["status"] = Invoice.LINK_SENT
        # take the units off the shared stock pool of the shop/channel sold
        # through -- a sale on any channel moves the same pool
        self._move_stock(self._units(items, validated_data["stock_point"]))
        return create_invoice(source=Invoice.SALE, lines=items, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        An edit moves stock only by what changed: the sold lines go back on
        the old shelf and the new lines come off the new one, netted per
        variant, so resaving the same lines moves nothing. Only an unpaid
        sale's lines or shop can change -- a paid one is returned through a
        refund, a cancelled one already put its units back.
        """
        items = validated_data.pop("items", None)
        invoice = Invoice.objects.select_for_update().get(pk=instance.pk)
        old_point = invoice.stock_point
        new_point = validated_data.get("stock_point", old_point)
        if items is not None and invoice.source != Invoice.SALE:
            raise serializers.ValidationError({"items": ["Repair and rental invoices are billed by their own modules; their lines can't be edited here."]})
        if invoice.source == Invoice.SALE and (items is not None or new_point.pk != old_point.pk):
            if invoice.status not in Invoice.OUTSTANDING:
                raise serializers.ValidationError({"detail": (
                    "Only an unpaid sale's items or shop can be changed. "
                    + ("Refund the returned items instead." if invoice.status in Invoice.SETTLED else "This invoice was cancelled.")
                )})
            old_lines = list(invoice.items.select_related("variant__product"))
            new_lines = old_lines if items is None else items
            changes = self._units(old_lines, old_point, sign=-1)
            changes.update(self._units(new_lines, new_point))  # Counter.update adds
            self._move_stock(changes)
            if items is not None:
                old_total = invoice.total
                invoice.items.all().delete()
                for line in items:
                    InvoiceItem.objects.create(invoice=invoice, **line)
                new_total = sum(line["qty"] * line["price"] for line in items)
                if new_total != old_total:
                    self._cancel_open_links(invoice)
                self._note_revision(invoice, old_lines, items, old_total, new_total)
        return super().update(invoice, validated_data)

    @staticmethod
    def _cancel_open_links(invoice):
        """A revised total makes any payment link already sent ask for the
        wrong amount: stop it, so the customer can only pay a fresh one."""
        from .payments import cancel_provider_link

        for link in invoice.payment_links.filter(status=PaymentLink.SENT):
            cancel_provider_link(link)
        invoice.payment_links.filter(status=PaymentLink.SENT).update(status=PaymentLink.CANCELLED)

    @staticmethod
    def _note_revision(invoice, old_lines, new_lines, old_total, new_total):
        """The revision in the staff activity log (who and when come from the
        request): the totals and every product added, removed or changed."""
        from accounts import activity

        def by_variant(lines):
            rows = {}
            for line in lines:
                variant, qty, price = (
                    (line["variant"], line["qty"], line["price"]) if isinstance(line, dict) else (line.variant, line.qty, line.price)
                )
                row = rows.setdefault(variant.pk, {"name": f"{variant.product.display_name} ({variant.spec})", "qty": 0, "amount": 0})
                row["qty"] += qty
                row["amount"] += qty * price
            return rows

        before, after = by_variant(old_lines), by_variant(new_lines)
        lines = []
        for pk in [*before, *(pk for pk in after if pk not in before)]:
            old, new = before.get(pk), after.get(pk)
            if not new:
                lines.append(f"removed {old['name']} ×{old['qty']}")
            elif not old:
                lines.append(f"added {new['name']} ×{new['qty']}")
            elif (old["qty"], old["amount"]) != (new["qty"], new["amount"]):
                lines.append(f"{new['name']} ×{old['qty']} ₹{old['amount']:,} → ×{new['qty']} ₹{new['amount']:,}")
        activity.note(
            invoice, "revised",
            f"Revised invoice {invoice.code}: ₹{old_total:,} → ₹{new_total:,}" + (f" ({'; '.join(lines)})" if lines else ""),
            changes={"total": (old_total, new_total)},
        )
