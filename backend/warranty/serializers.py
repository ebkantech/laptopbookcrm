from rest_framework import serializers

from repairs.models import RepairTicket
from sales.models import Invoice
from .models import Warranty


class WarrantySerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    party_phone = serializers.CharField(source="party.phone", read_only=True)
    party_email = serializers.CharField(source="party.email", read_only=True)
    status = serializers.CharField(read_only=True)
    terms_text = serializers.CharField(read_only=True)
    invoice_code = serializers.CharField(source="invoice.code", read_only=True)
    repair_code = serializers.CharField(source="repair_ticket.code", read_only=True)

    class Meta:
        model = Warranty
        fields = [
            "id", "party", "party_name", "party_phone", "party_email", "section", "item_label",
            "invoice", "invoice_code", "repair_ticket", "repair_code",
            "start_date", "end_date", "status", "terms_text", "notes", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        """
        This is the "condition should be met" rule: a Sales warranty
        can only be raised against an invoice that's actually been
        paid, and only for the same customer. A Repair warranty can
        only be raised against a ticket that's been delivered (i.e.
        it has a settled repair invoice) -- also for the same
        customer. Rental/Other warranties are entered by hand and
        don't need a linked record.
        """
        section = attrs.get("section", getattr(self.instance, "section", None))
        party = attrs.get("party", getattr(self.instance, "party", None))
        invoice = attrs.get("invoice", getattr(self.instance, "invoice", None))
        repair_ticket = attrs.get("repair_ticket", getattr(self.instance, "repair_ticket", None))

        if section == Warranty.SALES:
            if not invoice:
                raise serializers.ValidationError({"invoice": "Pick the paid invoice this warranty covers."})
            if invoice.status != Invoice.PAID:
                raise serializers.ValidationError({"invoice": "This invoice isn't marked Paid yet -- settle it before raising a sales warranty."})
            if invoice.party_id != party.id:
                raise serializers.ValidationError({"invoice": "That invoice doesn't belong to this customer."})

        if section == Warranty.REPAIR:
            if not repair_ticket:
                raise serializers.ValidationError({"repair_ticket": "Pick the completed repair ticket this warranty covers."})
            if not hasattr(repair_ticket, "invoice"):
                raise serializers.ValidationError({"repair_ticket": "This repair hasn't been delivered and settled yet -- warranty starts from delivery."})
            if repair_ticket.party_id != party.id:
                raise serializers.ValidationError({"repair_ticket": "That repair ticket doesn't belong to this customer."})

        if attrs.get("end_date") and attrs.get("start_date") and attrs["end_date"] <= attrs["start_date"]:
            raise serializers.ValidationError({"end_date": "End date must be after the start date."})

        return attrs
