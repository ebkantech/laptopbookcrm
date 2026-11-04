from django.db import models
from django.conf import settings


class Party(models.Model):
    """A customer, dealer, or rental account -- everything the CRM sells to."""
    RETAIL, DEALER, RENTAL = "Retail", "Dealer", "Rental"
    TYPE_CHOICES = [(RETAIL, "Retail"), (DEALER, "Dealer"), (RENTAL, "Rental")]
    INDIVIDUAL, BUSINESS, DEALER_CUSTOMER = "individual", "business", "dealer"
    CUSTOMER_CLASSIFICATION_CHOICES = [
        (INDIVIDUAL, "Individual"),
        (BUSINESS, "Business / Corporate"),
        (DEALER_CUSTOMER, "Dealer"),
    ]

    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=60, blank=True)
    joined = models.DateField()
    # This is intentionally separate from the legacy `type` field. A party can
    # be a rental customer and still be an individual, business, or dealer.
    customer_classification = models.CharField(
        max_length=12,
        choices=CUSTOMER_CLASSIFICATION_CHOICES,
        default=INDIVIDUAL,
    )
    # Task 3 (WhatsApp number verification pipeline): null = never checked
    # yet (e.g. a party created before this field existed, or the check
    # itself failed/skipped); True/False is a real answer from the
    # check-whatsapp-number call. Re-checked automatically whenever the
    # phone number changes -- see PartyViewSet.perform_create/_update.
    whatsapp_verified = models.BooleanField(null=True, blank=True, default=None)
    whatsapp_checked_at = models.DateTimeField(null=True, blank=True)

    # Task 6 security checklist ("portal tokens can't be replayed after
    # access is revoked"): portal tokens are stateless signed tokens with
    # no server-side session to delete, so revocation works by comparing
    # a token's issue time against this timestamp instead -- see
    # portal.auth.resolve_portal_token. Staff sets this via the
    # "Revoke portal access" action; it does not expire on its own.
    portal_access_revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "parties"

    def __str__(self):
        return self.name


class Message(models.Model):
    """A single WhatsApp/email exchange with a party -- powers the chat thread panel."""
    WHATSAPP, EMAIL, SMS = "whatsapp", "email", "sms"
    CHANNEL_CHOICES = [(WHATSAPP, "WhatsApp"), (EMAIL, "Email"), (SMS, "SMS")]
    IN, OUT = "in", "out"
    DIRECTION_CHOICES = [(IN, "Inbound"), (OUT, "Outbound")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="messages")
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    body = models.TextField()
    at = models.DateTimeField(auto_now_add=True)
    is_editable = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_party_messages")

    # WhatsApp Cloud API state of an outbound message the CRM tried to
    # send ("" = a CRM-only record: history, email, or written before
    # sending existed). "sent" means Meta ACCEPTED it; only Meta's
    # delivery webhook moves it on to delivered/read (or failed).
    # "unknown" = the outcome is uncertain (timeout etc.) -- it may have
    # gone out, so it is never resent without staff confirming.
    DELIVERY_SENDING, DELIVERY_SENT, DELIVERY_DELIVERED, DELIVERY_READ = "sending", "sent", "delivered", "read"
    DELIVERY_FAILED, DELIVERY_UNKNOWN, DELIVERY_SIMULATED = "failed", "unknown", "simulated"
    DELIVERY_CHOICES = [
        (DELIVERY_SENDING, "Sending"), (DELIVERY_SENT, "Sent to WhatsApp API"), (DELIVERY_DELIVERED, "Delivered"),
        (DELIVERY_READ, "Read"), (DELIVERY_FAILED, "Failed"), (DELIVERY_UNKNOWN, "Outcome unknown"),
        (DELIVERY_SIMULATED, "Not sent (simulation mode)"),
    ]
    delivery_status = models.CharField(max_length=10, choices=DELIVERY_CHOICES, blank=True, default="")
    provider_message_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    delivery_error = models.CharField(max_length=300, blank=True, default="")
    delivery_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["at"]


class MessageRevision(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="revisions")
    previous_body = models.TextField()
    edited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    edited_at = models.DateTimeField(auto_now_add=True)


class MessageHidden(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="hidden_for_users")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hidden_party_messages")
    hidden_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "user"], name="unique_user_hidden_party_message")]


def id_document_path(instance, filename):
    """Random name, extension from the checked content -- the client's filename is never used on disk."""
    import uuid

    from django.utils import timezone

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}[instance.content_type]
    return f"customer-ids/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class PartyIdDocument(models.Model):
    """
    A customer's identity document, recorded for rental agreements (parties.kyc).
    Aadhaar: the full number is NEVER stored -- only the masked form
    (XXXX XXXX 1234) -- and any copy kept must be the masked Aadhaar, as
    UIDAI requires. Every record needs the customer's consent, logged with
    who took it and when. "Verified" means a staff member checked the
    original document (or a later integration did) -- format checks alone
    only catch typing mistakes.
    """
    AADHAAR, PAN, DRIVING_LICENCE, PASSPORT, VOTER_ID, OTHER = "aadhaar", "pan", "driving_licence", "passport", "voter_id", "other"
    TYPE_CHOICES = [(AADHAAR, "Aadhaar"), (PAN, "PAN"), (DRIVING_LICENCE, "Driving licence"),
                    (PASSPORT, "Passport"), (VOTER_ID, "Voter ID"), (OTHER, "Other ID")]
    NOT_VERIFIED, FORMAT_OK, VERIFIED, FAILED = "not_verified", "format_ok", "verified", "failed"
    STATUS_CHOICES = [(NOT_VERIFIED, "Not verified"), (FORMAT_OK, "Format OK"), (VERIFIED, "Verified"), (FAILED, "Failed")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="id_documents")
    id_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    number = models.CharField(max_length=40, help_text="Aadhaar: masked only, e.g. XXXX XXXX 1234.")
    name_on_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=NOT_VERIFIED)
    check_note = models.CharField(max_length=200, blank=True, help_text="What the automatic format check found.")
    consent_at = models.DateTimeField()
    consent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    verify_method = models.CharField(max_length=40, blank=True)
    verify_note = models.CharField(max_length=200, blank=True)
    file = models.FileField(upload_to=id_document_path, max_length=255, blank=True)
    content_type = models.CharField(max_length=40, blank=True)
    original_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_id_type_display()} {self.number} ({self.party.name})"
