from rest_framework import serializers

from sales.models import Invoice
from sales.serializers import InvoiceItemSerializer
from .models import Message, Party


# WhatsApp Cloud API outcome of an outbound message (see parties/whatsapp.py).
# provider_message_id stays server-side; delivery_error is credential-free.
DELIVERY_FIELDS = ["delivery_status", "delivery_error", "delivery_updated_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "party", "channel", "direction", "body", "at", "is_editable", "edited_at", "is_deleted", *DELIVERY_FIELDS]
        read_only_fields = fields

    is_deleted = serializers.SerializerMethodField()

    def get_is_deleted(self, obj):
        return obj.deleted_at is not None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.deleted_at:
            data["body"] = "This message was deleted."
        return data


class MessageRecordSerializer(serializers.ModelSerializer):
    body = serializers.CharField(trim_whitespace=False)

    class Meta:
        model = Message
        fields = ["id", "party", "channel", "direction", "body", "at", "is_editable", "edited_at", "is_deleted", *DELIVERY_FIELDS]
        read_only_fields = ["id", "party", "direction", "at", "is_editable", "edited_at", "is_deleted", *DELIVERY_FIELDS]
    is_deleted = serializers.SerializerMethodField()

    def get_is_deleted(self, obj):
        return obj.deleted_at is not None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.deleted_at:
            data["body"] = "This message was deleted."
        return data

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Message content cannot be empty.")
        if len(value) > 20000:
            raise serializers.ValidationError("Message content cannot exceed 20,000 characters.")
        return value

    def validate_channel(self, value):
        if value not in (Message.WHATSAPP, Message.EMAIL, Message.PORTAL):
            raise serializers.ValidationError("Choose WhatsApp, email or the customer portal.")
        return value

    def validate(self, attrs):
        from .whatsapp import WHATSAPP_TEXT_LIMIT

        channel = attrs.get("channel") or (self.instance.channel if self.instance else None)
        body = attrs.get("body")
        if channel == Message.WHATSAPP and body is not None and len(body) > WHATSAPP_TEXT_LIMIT:
            raise serializers.ValidationError({"body": f"A WhatsApp message can't be longer than {WHATSAPP_TEXT_LIMIT:,} characters."})
        return attrs


class PartyInvoiceSerializer(serializers.ModelSerializer):
    """Lightweight invoice view for the party detail popup -- no need to
    repeat the party's own name/id back to itself here."""
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    total = serializers.IntegerField(read_only=True)
    item_count = serializers.SerializerMethodField()
    balance_due = serializers.IntegerField(read_only=True)
    # "Payment link sent" is also the default status of a new unpaid invoice,
    # so the popup needs to know whether a link really is out with the customer.
    link_sent = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "source", "date", "status", "stock_point_name", "total", "balance_due",
            "item_count", "pay_method", "recurring_interval", "due_date", "link_sent",
        ]

    def get_link_sent(self, obj):
        return any(link.status == "sent" for link in obj.payment_links.all())

    def get_item_count(self, obj):
        # products only: a discount (or a "Less: advance" line) isn't an item
        return sum(1 for item in obj.items.all() if item.item_kind != "discount" and item.price >= 0)


class PartyInvoiceItemSerializer(InvoiceItemSerializer):
    """One invoice line for the party popup: the sales serializer's fields
    plus the product and variant split out, so each can be shown and copied
    on its own. line_total is qty x price -- the same sum Invoice.total adds up."""
    product = serializers.SerializerMethodField()
    spec = serializers.SerializerMethodField()
    colour = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta(InvoiceItemSerializer.Meta):
        fields = InvoiceItemSerializer.Meta.fields + ["product", "spec", "colour", "line_total"]

    def get_product(self, obj):
        # repair/rental lines are services or rent: their description is the item
        if obj.description or not obj.variant_id:
            return obj.description
        return obj.variant.product.display_name

    def get_spec(self, obj):
        return obj.variant.spec if obj.variant_id else ""

    def get_colour(self, obj):
        return obj.variant.colour if obj.variant_id else ""

    def get_line_total(self, obj):
        return obj.qty * obj.price


class PartySerializer(serializers.ModelSerializer):
    # New customer records need complete contact details. Declaring these
    # explicitly also makes the requirement apply to direct API callers;
    # DRF still permits omitted fields on PATCH requests.
    name = serializers.CharField(max_length=120, allow_blank=False, trim_whitespace=True)
    type = serializers.ChoiceField(choices=Party.TYPE_CHOICES)
    phone = serializers.CharField(max_length=20, allow_blank=False, trim_whitespace=True)
    # required for customers (invoices and portal links go to it); a
    # Supplier may have none -- see validate()
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True, trim_whitespace=True)
    city = serializers.CharField(max_length=60, allow_blank=False, trim_whitespace=True)

    total_spent = serializers.SerializerMethodField()
    invoice_count = serializers.SerializerMethodField()
    amount_due = serializers.SerializerMethodField()
    # customer ID on file: "verified" / "unverified" / "none" (parties.kyc)
    kyc_status = serializers.SerializerMethodField()
    # a supplier: what we still owe them (negative = an advance with them); None for customers
    supplier_owed = serializers.SerializerMethodField()

    def get_kyc_status(self, obj):
        from .kyc import kyc_status

        return kyc_status(obj)

    class Meta:
        model = Party
        fields = [
            "id", "name", "type", "customer_classification", "phone", "email", "gstin", "city", "joined", "kyc_status",
            "total_spent", "invoice_count", "amount_due", "whatsapp_verified", "whatsapp_checked_at",
            "portal_access_revoked_at", "supplier_owed",
        ]

    def to_internal_value(self, data):
        # email is required unless the party is a Supplier -- reported together
        # with any other missing field, as a required field would be
        errors, attrs = {}, None
        try:
            attrs = super().to_internal_value(data)
        except serializers.ValidationError as exc:
            errors = dict(exc.detail)
        party_type = data.get("type") or (self.instance.type if self.instance else None)
        email = data.get("email", self.instance.email if self.instance else "")
        checks_email = self.instance is None or not self.partial or "email" in data or "type" in data
        if checks_email and party_type != Party.SUPPLIER and not str(email or "").strip() and "email" not in errors:
            errors["email"] = ["This field is required."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate_phone(self, value):
        from crmbook_backend.phones import clean_customer_phone

        # an existing number left as it was is not re-checked, so an old
        # record can still be edited (name, city...) without fixing it first
        if self.instance and value == self.instance.phone:
            return value
        return clean_customer_phone(value)

    def get_supplier_owed(self, obj):
        if obj.type != Party.SUPPLIER:
            return None
        from catalog.purchases import balance

        return balance(obj)[2]

    def get_total_spent(self, obj):
        return sum(inv.total for inv in obj.invoices.all() if not inv.is_deposit)

    def get_amount_due(self, obj):
        return sum(inv.balance_due for inv in obj.invoices.all())

    def get_invoice_count(self, obj):
        return obj.invoices.count()


class PartyDetailSerializer(PartySerializer):
    messages = serializers.SerializerMethodField()
    invoices = PartyInvoiceSerializer(many=True, read_only=True)

    class Meta(PartySerializer.Meta):
        fields = PartySerializer.Meta.fields + ["messages", "invoices"]

    def get_messages(self, obj):
        user = self.context.get("request").user if self.context.get("request") else None
        messages = obj.messages.all()
        if user and user.is_authenticated:
            messages = messages.exclude(hidden_for_users__user=user)
        return MessageSerializer(messages, many=True, context=self.context).data
