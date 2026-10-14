from rest_framework import serializers

from sales.models import Invoice
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
        if value not in (Message.WHATSAPP, Message.EMAIL):
            raise serializers.ValidationError("Choose WhatsApp or email.")
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

    class Meta:
        model = Invoice
        fields = [
            "id", "code", "source", "date", "status", "stock_point_name", "total",
            "item_count", "pay_method", "recurring_interval",
        ]

    def get_item_count(self, obj):
        return obj.items.count()


class PartySerializer(serializers.ModelSerializer):
    # New customer records need complete contact details. Declaring these
    # explicitly also makes the requirement apply to direct API callers;
    # DRF still permits omitted fields on PATCH requests.
    name = serializers.CharField(max_length=120, allow_blank=False, trim_whitespace=True)
    type = serializers.ChoiceField(choices=Party.TYPE_CHOICES)
    phone = serializers.CharField(max_length=20, allow_blank=False, trim_whitespace=True)
    email = serializers.EmailField(max_length=254, allow_blank=False, trim_whitespace=True)
    city = serializers.CharField(max_length=60, allow_blank=False, trim_whitespace=True)

    total_spent = serializers.SerializerMethodField()
    invoice_count = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = [
            "id", "name", "type", "customer_classification", "phone", "email", "gstin", "city", "joined",
            "total_spent", "invoice_count", "whatsapp_verified", "whatsapp_checked_at",
            "portal_access_revoked_at",
        ]

    def validate_phone(self, value):
        digits = "".join(character for character in value if character.isdigit())
        if not 10 <= len(digits) <= 15:
            raise serializers.ValidationError("Enter a valid phone number with 10 to 15 digits.")
        return value

    def get_total_spent(self, obj):
        return sum(inv.total for inv in obj.invoices.all())

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
