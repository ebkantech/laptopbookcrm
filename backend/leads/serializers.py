from rest_framework import serializers

from accounts.store_scope import StoreScope
from sales.models import Invoice
from . import services
from .models import Lead, LeadApproval, LeadEvent, LeadPartIssue, LeadQuote, LeadQuoteLine


def user_name(user):
    return (user.get_full_name() or user.username) if user else ""


class QuoteLineSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()

    class Meta:
        model = LeadQuoteLine
        fields = ["id", "kind", "description", "qty", "price", "amount", "part", "variant", "deducted"]

    def get_amount(self, obj):
        return obj.qty * obj.price


class QuoteSerializer(serializers.ModelSerializer):
    lines = QuoteLineSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    prepared_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LeadQuote
        fields = ["id", "version", "status", "note", "lines", "total", "on_behalf", "prepared_by_name", "created_at"]

    def get_prepared_by_name(self, obj):
        return user_name(obj.prepared_by)


class EventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = LeadEvent
        fields = ["id", "event", "text", "actor_name", "created_at"]

    def get_actor_name(self, obj):
        return user_name(obj.actor)


class ApprovalSerializer(serializers.ModelSerializer):
    decided_by_name = serializers.SerializerMethodField()
    quote_version = serializers.IntegerField(source="quote.version", read_only=True)

    class Meta:
        model = LeadApproval
        fields = ["id", "status", "source", "reason", "quote_version", "expires_at", "decided_at", "decided_by_name", "created_at"]

    def get_decided_by_name(self, obj):
        return user_name(obj.decided_by)


class PartIssueSerializer(serializers.ModelSerializer):
    technician_name = serializers.SerializerMethodField()
    outstanding = serializers.IntegerField(read_only=True)
    lead_code = serializers.CharField(source="lead.code", read_only=True)
    lead_status = serializers.CharField(source="lead.status", read_only=True)
    due_now = serializers.SerializerMethodField()

    class Meta:
        model = LeadPartIssue
        fields = ["id", "lead", "lead_code", "lead_status", "kind", "description", "qty_issued", "qty_used", "qty_returned", "qty_written_off",
                  "outstanding", "technician", "technician_name", "issued_at", "note", "due_now"]

    def get_technician_name(self, obj):
        return user_name(obj.technician)

    def get_due_now(self, obj):
        # the job is over, so what is left must come back now
        return obj.outstanding > 0 and obj.lead.status in Lead.FINISHED


def _invoice_row(inv):
    return {"id": inv.id, "code": inv.code, "status": inv.status, "total": inv.total, "is_advance": inv.is_advance,
            "pay_method": inv.pay_method, "paid_on": inv.paid_on}


def allowed_actions(lead, user):
    """What this user can do with the job right now -- the UI shows
    exactly these buttons."""
    s = lead.status
    p = user.has_perm_code
    manage = p("leads.manage")
    works = (p("leads.work") or manage) and services.can_work(user, lead)
    quotes = (p("leads.quote") or manage) and services.can_work(user, lead)
    collect = p("leads.collect") or manage
    acts = []
    if (p("leads.assign") or manage) and s in (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING):
        acts.append("assign")
    if manage and s in (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING):
        acts += ["edit", "reschedule"]
    if works and s == Lead.ASSIGNED:
        acts.append("check_in")
    if works and s in (Lead.VISITING, Lead.DIAGNOSED):
        acts.append("diagnose")
    if quotes and (s in (Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED) or (s == Lead.VISITING and lead.diagnosis)):
        acts.append("quote")
    if quotes and s in (Lead.DIAGNOSED, Lead.AWAITING) and services.current_quote(lead):
        acts.append("send_link")
    if p("leads.approve") and s in (Lead.DIAGNOSED, Lead.AWAITING) and services.current_quote(lead):
        acts.append("approve")
    if works and s == Lead.APPROVED:
        acts.append("start")
    if works and s == Lead.IN_WORK:
        acts.append("complete")
    if (works or manage) and s in (Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK):
        acts.append("to_store")
    if manage and s in (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK):
        acts.append("advance")
    if collect and s in (Lead.WORK_DONE, Lead.REJECTED, Lead.TO_STORE) and not lead.checked_out_at:
        acts.append("collect")
    if p("leads.parts") and s in services.ISSUE_STATES and lead.assigned_to_id:
        acts.append("issue_parts")
    if p("leads.parts") and any(i.outstanding > 0 for i in lead.part_issues.all()):
        acts.append("return_parts")
        if manage:
            acts.append("write_off_parts")
    if collect and any(i.is_advance and i.status in Invoice.OUTSTANDING for i in lead.invoices.all()):
        acts.append("collect_advance")
    if manage and s == Lead.WORK_DONE:
        acts.append("close_credit")
    if (manage or works) and s in (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK):
        acts.append("cancel")
    return acts


class LeadListSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True)
    assigned_to_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    quote_total = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id", "code", "lead_type", "status", "status_label", "priority", "party", "party_name", "stock_point", "stock_point_name",
            "contact_name", "contact_phone", "site_address", "map_url", "device", "issue", "preferred_at", "assigned_to",
            "assigned_to_name", "visit_charge", "advance_amount", "quote_total", "checked_in_at", "checked_out_at", "created_at",
        ]

    def get_assigned_to_name(self, obj):
        return user_name(obj.assigned_to)

    def get_quote_total(self, obj):
        q = services.current_quote(obj)
        return q.total if q else None


class LeadDetailSerializer(LeadListSerializer):
    quote = serializers.SerializerMethodField()
    quotes = QuoteSerializer(many=True, read_only=True)
    approvals = ApprovalSerializer(many=True, read_only=True)
    events = serializers.SerializerMethodField()
    invoices = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    advance_received = serializers.SerializerMethodField()
    party_phone = serializers.CharField(source="party.phone", read_only=True)
    repair_ticket_code = serializers.CharField(source="repair_ticket.code", read_only=True, default=None)
    parts = PartIssueSerializer(source="part_issues", many=True, read_only=True)

    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + [
            "diagnosis", "diagnosed_at", "work_notes", "work_started_at", "work_done_at", "closed_on_credit", "credit_reason",
            "cancel_reason", "reject_reason", "check_in_lat", "check_in_lng", "quote", "quotes", "approvals", "events",
            "invoices", "actions", "advance_received", "party_phone", "repair_ticket", "repair_ticket_code", "parts",
        ]

    def get_quote(self, obj):
        q = services.current_quote(obj)
        return QuoteSerializer(q).data if q else None

    def get_events(self, obj):
        """
        The job's timeline. Whoever assigns jobs (leads.assign, Admins, the
        Owner) sees all of it; a technician sees the job being created and
        everything from its current assignment on -- not who had it before
        or what happened while they did.
        """
        events = list(obj.events.select_related("actor").all())
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not _sees_full_timeline(user):
            assigned = [i for i, e in enumerate(events) if e.event == "assigned"]
            if len(assigned) > 1:  # reassigned: start at the current assignment
                start = assigned[-1]
                events = [e for i, e in enumerate(events) if i >= start or e.event == "created"]
        return EventSerializer(events, many=True).data

    def get_invoices(self, obj):
        return [_invoice_row(i) for i in obj.invoices.all().order_by("id")]

    def get_actions(self, obj):
        return allowed_actions(obj, self.context["request"].user)

    def get_advance_received(self, obj):
        return services.advance_received(obj)


class LeadWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            "party", "stock_point", "contact_name", "contact_phone", "site_address", "map_url", "device", "issue",
            "priority", "preferred_at", "assigned_to", "visit_charge", "advance_amount",
        ]

    def validate_site_address(self, value):
        if len(value.strip()) < 6:
            raise serializers.ValidationError("Enter the full site address.")
        return value.strip()

    def validate_issue(self, value):
        if len(value.strip()) < 5:
            raise serializers.ValidationError("Describe the problem.")
        return value.strip()

    def validate_contact_phone(self, value):
        from crmbook_backend.phones import clean_customer_phone

        return clean_customer_phone(value) if (value or "").strip() else value

    def validate_visit_charge(self, value):
        if value > 100000:
            raise serializers.ValidationError("That visit charge looks too high.")
        return value

    def validate(self, attrs):
        tech = attrs.get("assigned_to")
        if tech and not (tech.has_perm_code("leads.work")):
            raise serializers.ValidationError({"assigned_to": "That person can't be given on-site jobs."})
        request = self.context.get("request")
        if tech and tech.staff_kind == "outsourced" and request is not None and not request.user.has_perm_code("leads.outsource"):
            raise serializers.ValidationError({"assigned_to": "Only a Super Admin or Admin can give a job to an outsourced technician."})
        return attrs


class PublicApprovalSerializer(serializers.ModelSerializer):
    lead_code = serializers.CharField(source="lead.code")
    customer_name = serializers.CharField(source="lead.party.name")
    device = serializers.CharField(source="lead.device")
    issue = serializers.CharField(source="lead.issue")
    diagnosis = serializers.CharField(source="lead.diagnosis")
    site_address = serializers.CharField(source="lead.site_address")
    advance_amount = serializers.IntegerField(source="lead.advance_amount")
    lines = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    version = serializers.IntegerField(source="quote.version")
    note = serializers.CharField(source="quote.note")

    class Meta:
        model = LeadApproval
        fields = ["status", "lead_code", "customer_name", "device", "issue", "diagnosis", "site_address", "advance_amount",
                  "version", "note", "lines", "total", "expires_at", "decided_at", "reason"]

    def get_lines(self, obj):
        return [{"kind": l.kind, "description": l.description, "qty": l.qty, "price": l.price, "amount": l.qty * l.price}
                for l in obj.quote.lines.all()]

    def get_total(self, obj):
        return obj.quote.total


class PublicDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject", "request_changes"])
    consent = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


def _sees_full_timeline(user):
    from accounts.staff import is_staff_admin

    return user.is_superuser or is_staff_admin(user) or user.has_perm_code("leads.assign")
