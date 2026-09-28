from django.db import models


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
    WHATSAPP, EMAIL = "whatsapp", "email"
    CHANNEL_CHOICES = [(WHATSAPP, "WhatsApp"), (EMAIL, "Email")]
    IN, OUT = "in", "out"
    DIRECTION_CHOICES = [(IN, "Inbound"), (OUT, "Outbound")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="messages")
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    body = models.TextField()
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]
