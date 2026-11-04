"""
Workflow for on-site service jobs (Leads).

new -> assigned -> visiting -> diagnosed -> awaiting_approval -> approved
    -> in_work -> work_done -> closed
with side exits: rejected (client declined; the visit charge is invoiced),
cancelled. Nothing is worked on before the client (or an Admin on their
behalf, with a reason) approves a quote; stock is taken off the shelf only
when the work is marked done; the job is checked out when the bill is paid.
"""
import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import quote as urlquote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from catalog.models import Part, PartStock, Stock, Variant
from crmbook_backend.notify import notify_staff, send_whatsapp
from .models import Lead, LeadApproval, LeadEvent, LeadPartIssue, LeadQuote, LeadQuoteLine

APPROVAL_LINK_TTL = timedelta(hours=24)
MAX_LINES = 40


class LeadApprovalLinkGone(APIException):
    status_code = 410
    default_detail = "This approval link is invalid or has expired."
    default_code = "lead_approval_link_gone"


class LeadApprovalConflict(APIException):
    status_code = 409
    default_detail = "A final decision has already been recorded for this job."
    default_code = "lead_approval_conflict"


def _err(message, field="detail"):
    return ValidationError({field: message})


def log(lead, event, text="", actor=None):
    return LeadEvent.objects.create(lead=lead, event=event, text=text[:300], actor=actor)


def next_lead_code():
    highest = 0
    for code in Lead.objects.filter(code__regex=r"^LD-[0-9]+$").values_list("code", flat=True):
        highest = max(highest, int(code[3:]))
    return f"LD-{highest + 1:04d}"


def lock(lead):
    # of=("self",): lock only the job row. Locking the joined rows too is
    # refused by PostgreSQL when assigned_to is empty (nullable join).
    return Lead.objects.select_for_update(of=("self",)).select_related("party", "stock_point", "assigned_to").get(pk=lead.pk)


def sees_all_jobs(user):
    return user.has_perm_code("leads.assign") or user.has_perm_code("leads.manage") or user.has_perm_code("leads.create")


def can_work(user, lead):
    """The assigned technician, or an admin who manages jobs."""
    return lead.assigned_to_id == user.id or user.has_perm_code("leads.manage") or user.has_perm_code("leads.assign")


def _require_work(user, lead):
    if not user.has_perm_code("leads.work") and not user.has_perm_code("leads.manage"):
        raise PermissionDenied("You do not have permission to work on on-site jobs.")
    if not can_work(user, lead):
        raise PermissionDenied("This job is assigned to someone else.")


def _state(lead, allowed, action):
    if lead.status not in allowed:
        names = ", ".join(dict(Lead.STATUS_CHOICES)[s] for s in allowed)
        raise _err(f"You can only {action} while the job is: {names}. It is now {lead.get_status_display()}.")


# ---------------------------------------------------------------- creation

@transaction.atomic
def create_lead(user, **fields):
    for attempt in range(5):
        try:
            with transaction.atomic():
                lead = Lead.objects.create(code=next_lead_code(), created_by=user, **fields)
                break
        except IntegrityError:
            if attempt == 4:
                raise
    log(lead, "created", f"Job {lead.code} created", user)
    if lead.advance_amount:
        _make_advance(lead, lead.advance_amount, user)
    if lead.assigned_to_id:
        lead.status = Lead.ASSIGNED
        lead.save(update_fields=["status"])
        log(lead, "assigned", f"Assigned to {lead.assigned_to}", user)
        _tell_technician(lead)
    return lead


def _tell_technician(lead):
    tech = lead.assigned_to
    if not tech:
        return
    text = f"New on-site job {lead.code}: {lead.party.name}, {lead.site_address}. {lead.issue[:120]}"
    phone = getattr(tech, "phone", "") or ""
    if phone:
        send_whatsapp(phone, text)
    notify_staff("lead_assigned", f"On-site job {lead.code} assigned", text)


@transaction.atomic
def assign(lead, technician, user):
    lead = lock(lead)
    _state(lead, (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING), "assign")
    lead.assigned_to = technician
    if lead.status == Lead.NEW:
        lead.status = Lead.ASSIGNED
    lead.save(update_fields=["assigned_to", "status"])
    log(lead, "assigned", f"Assigned to {technician}", user)
    _tell_technician(lead)
    return lead


@transaction.atomic
def reschedule(lead, user, preferred_at, reason):
    lead = lock(lead)
    _state(lead, (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING), "reschedule")
    if not preferred_at:
        raise _err("Pick the new visit date and time.", "preferred_at")
    lead.preferred_at = preferred_at
    lead.save(update_fields=["preferred_at"])
    log(lead, "rescheduled", f"Visit moved to {timezone.localtime(preferred_at):%d %b %Y %H:%M}" + (f" -- {reason}" if reason else ""), user)
    return lead


# ------------------------------------------------------------------- visit

@transaction.atomic
def check_in(lead, user, lat=None, lng=None, note=""):
    lead = lock(lead)
    _require_work(user, lead)
    _state(lead, (Lead.ASSIGNED,), "check in")
    lead.status = Lead.VISITING
    lead.checked_in_at = timezone.now()
    lead.check_in_lat, lead.check_in_lng = lat, lng
    lead.save(update_fields=["status", "checked_in_at", "check_in_lat", "check_in_lng"])
    log(lead, "checked_in", "Reached the site" + (f" -- {note}" if note else ""), user)
    return lead


@transaction.atomic
def diagnose(lead, user, diagnosis):
    lead = lock(lead)
    _require_work(user, lead)
    _state(lead, (Lead.VISITING, Lead.DIAGNOSED), "record the diagnosis")
    diagnosis = (diagnosis or "").strip()
    if not diagnosis:
        raise _err("Write what you found.", "diagnosis")
    lead.diagnosis = diagnosis[:4000]
    lead.diagnosed_at = timezone.now()
    lead.status = Lead.DIAGNOSED
    lead.save(update_fields=["diagnosis", "diagnosed_at", "status"])
    log(lead, "diagnosed", "Diagnosis recorded", user)
    return lead


# ------------------------------------------------------------------- quote

def _clean_lines(raw_lines, stock_point_id):
    if not isinstance(raw_lines, list) or not raw_lines:
        raise _err("Add at least one line to the bill.", "lines")
    if len(raw_lines) > MAX_LINES:
        raise _err(f"A bill can have at most {MAX_LINES} lines.", "lines")
    from catalog.models import Part, Variant

    out = []
    for i, raw in enumerate(raw_lines, 1):
        if not isinstance(raw, dict):
            raise _err(f"Line {i} is not valid.", "lines")
        kind = raw.get("kind")
        if kind not in (LeadQuoteLine.LABOUR, LeadQuoteLine.PART, LeadQuoteLine.PRODUCT):
            raise _err(f"Line {i}: choose labour, part or product.", "lines")
        try:
            qty, price = int(raw.get("qty", 1)), int(raw.get("price", 0))
        except (TypeError, ValueError):
            raise _err(f"Line {i}: quantity and price must be numbers.", "lines")
        if qty < 1 or qty > 999:
            raise _err(f"Line {i}: quantity must be between 1 and 999.", "lines")
        if price < 0 or price > 10_000_000:
            raise _err(f"Line {i}: price must be zero or more.", "lines")
        description = (raw.get("description") or "").strip()
        part = variant = None
        if kind == LeadQuoteLine.PART:
            try:
                part = Part.objects.get(pk=raw.get("part"))
            except (Part.DoesNotExist, TypeError, ValueError):
                raise _err(f"Line {i}: pick a spare part from the list.", "lines")
            description = description or part.name
        elif kind == LeadQuoteLine.PRODUCT:
            try:
                variant = Variant.objects.select_related("product").get(pk=raw.get("variant"))
            except (Variant.DoesNotExist, TypeError, ValueError):
                raise _err(f"Line {i}: pick a product from the list.", "lines")
            description = description or f"{variant.product.display_name} ({variant.spec})"
        if not description:
            raise _err(f"Line {i}: describe the work.", "lines")
        out.append(dict(kind=kind, description=description[:160], qty=qty, price=price, part=part, variant=variant))
    return out


@transaction.atomic
def save_quote(lead, user, raw_lines, note=""):
    """A new immutable version of the bill. The visit charge is added as
    the first line. Revising an approved or pending bill withdraws that
    approval -- the client must approve the new version."""
    lead = lock(lead)
    if not (user.has_perm_code("leads.quote") or user.has_perm_code("leads.manage")):
        raise PermissionDenied("You do not have permission to prepare bills.")
    if not can_work(user, lead):
        raise PermissionDenied("This job is assigned to someone else.")
    _state(lead, (Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED), "prepare the bill")
    if lead.status == Lead.VISITING and not lead.diagnosis:
        raise _err("Record the diagnosis before preparing the bill.")
    lines = _clean_lines(raw_lines, lead.stock_point_id)
    on_behalf = lead.assigned_to_id != user.id
    now = timezone.now()
    lead.approvals.filter(status=LeadApproval.PENDING).update(status=LeadApproval.REVOKED)
    lead.approvals.filter(status=LeadApproval.APPROVED).update(status=LeadApproval.REVOKED)
    lead.quotes.exclude(status=LeadQuote.SUPERSEDED).update(status=LeadQuote.SUPERSEDED)
    version = (lead.quotes.aggregate(v=Max("version"))["v"] or 0) + 1
    quote = LeadQuote.objects.create(lead=lead, version=version, note=(note or "")[:300], prepared_by=user, on_behalf=on_behalf)
    if lead.visit_charge:
        LeadQuoteLine.objects.create(quote=quote, kind=LeadQuoteLine.VISIT, description="Visit charge", qty=1, price=lead.visit_charge)
    for line in lines:
        LeadQuoteLine.objects.create(quote=quote, **line)
    if lead.status != Lead.DIAGNOSED:
        lead.status = Lead.DIAGNOSED
        lead.save(update_fields=["status"])
    suffix = " (on the technician's behalf)" if on_behalf else ""
    log(lead, "quote_saved", f"Bill v{version} prepared{suffix}: ₹{quote.total}", user)
    return quote


def current_quote(lead):
    return lead.quotes.exclude(status=LeadQuote.SUPERSEDED).order_by("-version").first()


# ---------------------------------------------------------- approval link

def approval_token_hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_approval_url(raw):
    return f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/lead-approval/{raw}"


def build_whatsapp_url(phone, message):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = f"91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        digits = f"91{digits[1:]}"
    target = f"https://wa.me/{digits}" if 8 <= len(digits) <= 15 else "https://wa.me/"
    return f"{target}?text={urlquote(message, safe='')}"


def approval_message(lead, url):
    return (
        f"Hello {lead.party.name}, your laptop service bill for job {lead.code} is ready. "
        f"Please review and approve it here (valid for 24 hours): {url}"
    )


@transaction.atomic
def issue_approval_link(lead, user, send=False):
    lead = lock(lead)
    if not (user.has_perm_code("leads.quote") or user.has_perm_code("leads.manage")):
        raise PermissionDenied("You do not have permission to send bills for approval.")
    if not can_work(user, lead):
        raise PermissionDenied("This job is assigned to someone else.")
    _state(lead, (Lead.DIAGNOSED, Lead.AWAITING), "send the bill for approval")
    quote = current_quote(lead)
    if not quote:
        raise _err("Prepare the bill first.")
    lead.approvals.filter(status__in=(LeadApproval.PENDING,)).update(status=LeadApproval.REVOKED)
    raw = secrets.token_urlsafe(32)
    approval = LeadApproval.objects.create(
        lead=lead, quote=quote, token_hash=approval_token_hash(raw), requested_by=user,
        expires_at=timezone.now() + APPROVAL_LINK_TTL,
    )
    quote.status = LeadQuote.SENT
    quote.save(update_fields=["status"])
    lead.status = Lead.AWAITING
    lead.save(update_fields=["status"])
    url = build_approval_url(raw)
    message = approval_message(lead, url)
    log(lead, "link_issued", f"Approval link for bill v{quote.version} created (24 hours)", user)
    delivery = None
    if send:
        delivery = send_whatsapp(lead.contact_phone or lead.party.phone, message)
        log(lead, "link_sent", "Approval link sent on WhatsApp", user)
    return approval, url, build_whatsapp_url(lead.contact_phone or lead.party.phone, message), delivery


def get_public_approval(raw, for_update=False):
    if not raw or len(raw) > 200:
        raise NotFound("This approval link is invalid or has expired.")
    qs = LeadApproval.objects.select_related("lead__party", "quote")
    if for_update:
        qs = qs.select_for_update(of=("self",))
    try:
        approval = qs.get(token_hash=approval_token_hash(raw))
    except LeadApproval.DoesNotExist as exc:
        raise NotFound("This approval link is invalid or has expired.") from exc
    if approval.expires_at and timezone.now() >= approval.expires_at:
        if approval.status == LeadApproval.PENDING:
            LeadApproval.objects.filter(pk=approval.pk, status=LeadApproval.PENDING).update(status=LeadApproval.EXPIRED)
        raise LeadApprovalLinkGone()
    if approval.status in (LeadApproval.EXPIRED, LeadApproval.REVOKED):
        raise LeadApprovalLinkGone()
    return approval


def _approve(lead, approval, source, user=None, reason="", ip=None, ua=""):
    approval.status = LeadApproval.APPROVED
    approval.source, approval.reason = source, reason[:500]
    approval.decided_by, approval.decided_at = user, timezone.now()
    approval.decided_ip, approval.decided_user_agent = ip, ua[:300]
    approval.save()
    approval.quote.status = LeadQuote.APPROVED
    approval.quote.save(update_fields=["status"])
    lead.status = Lead.APPROVED
    lead.save(update_fields=["status"])
    who = "the client" if source == LeadApproval.CUSTOMER else f"{user} on the client's behalf"
    log(lead, "approved", f"Bill v{approval.quote.version} (₹{approval.quote.total}) approved by {who}" + (f" -- {reason}" if reason else ""), user)
    notify_staff("lead_approved", f"On-site bill approved -- {lead.code}", f"{lead.party.name} approved the bill for {lead.code} (₹{approval.quote.total}).")


def _reject(lead, approval, reason, ip=None, ua=""):
    approval.status = LeadApproval.REJECTED
    approval.source = LeadApproval.CUSTOMER
    approval.reason = reason[:500]
    approval.decided_at = timezone.now()
    approval.decided_ip, approval.decided_user_agent = ip, ua[:300]
    approval.save()
    approval.quote.status = LeadQuote.REJECTED
    approval.quote.save(update_fields=["status"])
    lead.status = Lead.REJECTED
    lead.reject_reason = reason[:500]
    lead.save(update_fields=["status", "reject_reason"])
    log(lead, "rejected", "Client declined the bill" + (f": {reason}" if reason else ""))
    flag_returns(lead)
    invoice = raise_visit_invoice(lead)
    if not invoice:
        _check_out(lead)


def customer_decide(raw, decision, consent=False, reason="", ip_address=None, user_agent=""):
    reason = (reason or "").strip()
    if decision not in ("approve", "reject", "request_changes"):
        raise ValidationError({"decision": "Choose approve, reject, or ask for changes."})
    if decision == "approve" and consent is not True:
        raise ValidationError({"consent": "Confirm that you reviewed the bill and the charges."})
    if decision == "request_changes" and not reason:
        raise ValidationError({"reason": "Tell us what you would like changed."})
    if len(reason) > 500:
        raise ValidationError({"reason": "Keep it under 500 characters."})
    desired = {"approve": LeadApproval.APPROVED, "reject": LeadApproval.REJECTED, "request_changes": "changes_requested"}[decision]
    try:
        with transaction.atomic():
            approval = get_public_approval(raw, for_update=True)
            if approval.status in (LeadApproval.APPROVED, LeadApproval.REJECTED, "changes_requested"):
                if approval.status == desired:
                    return approval
                raise LeadApprovalConflict("A different decision has already been recorded on this link.")
            if approval.status != LeadApproval.PENDING:
                raise LeadApprovalLinkGone()
            lead = lock(approval.lead)
            if lead.status != Lead.AWAITING:
                raise LeadApprovalConflict("This job is no longer waiting for approval.")
            approval = LeadApproval.objects.select_related("quote").get(pk=approval.pk)
            if decision == "approve":
                _approve(lead, approval, LeadApproval.CUSTOMER, None, reason, ip_address, user_agent)
            elif decision == "reject":
                _reject(lead, approval, reason, ip_address, user_agent)
            else:
                approval.status, approval.source, approval.reason = "changes_requested", LeadApproval.CUSTOMER, reason
                approval.decided_at, approval.decided_ip, approval.decided_user_agent = timezone.now(), ip_address, (user_agent or "")[:300]
                approval.save()
                lead.status = Lead.DIAGNOSED
                lead.save(update_fields=["status"])
                log(lead, "changes_requested", f"Client asked for changes: {reason}")
                notify_staff("lead_changes_requested", f"Client wants changes -- {lead.code}", f"{lead.party.name}: {reason}")
            approval.refresh_from_db()
            return approval
    except IntegrityError as exc:
        raise LeadApprovalConflict() from exc


@transaction.atomic
def approve_on_behalf(lead, user, reason):
    if not user.has_perm_code("leads.approve"):
        raise PermissionDenied("You do not have permission to approve on-site bills.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reason is required for Admin or Super Admin approval."})
    lead = lock(lead)
    _state(lead, (Lead.DIAGNOSED, Lead.AWAITING), "approve the bill")
    quote = current_quote(lead)
    if not quote:
        raise _err("Prepare the bill first.")
    lead.approvals.filter(status=LeadApproval.PENDING).update(status=LeadApproval.REVOKED)
    source = LeadApproval.SUPERADMIN if user.is_superuser else LeadApproval.ADMIN
    approval = LeadApproval.objects.create(lead=lead, quote=quote, requested_by=user)
    _approve(lead, approval, source, user, reason)
    return approval


# -------------------------------------------------------------- invoicing

def _party_phone(lead):
    return lead.contact_phone or lead.party.phone


def raise_visit_invoice(lead):
    """Bill just the visit when the client turns the quote down."""
    from sales.models import Invoice
    from sales.services import create_invoice

    if not lead.visit_charge or lead.invoices.filter(is_advance=False).exclude(status=Invoice.CANCELLED).exists():
        return None
    today = timezone.localdate()
    invoice = create_invoice(
        source=Invoice.ONSITE, lead=lead, party=lead.party, stock_point=lead.stock_point, date=today,
        status=Invoice.LINK_SENT,
        lines=[{"description": f"Visit charge for {lead.code} (quote declined)", "qty": 1, "price": lead.visit_charge}],
    )
    log(lead, "visit_invoice", f"Visit charge invoice {invoice.code} raised: ₹{lead.visit_charge}")
    return invoice


@transaction.atomic
def raise_advance(lead, user, amount):
    """Asking for an advance is an Admin / Super Admin decision -- a
    technician can collect one that was asked for, but not raise it."""
    if not user.has_perm_code("leads.manage"):
        raise PermissionDenied("Only an Admin or Super Admin can ask for an advance.")
    lead = lock(lead)
    _state(lead, (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK), "ask for an advance")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise _err("Enter the advance amount.", "amount")
    if amount <= 0 or amount > 1_000_000:
        raise _err("The advance must be more than zero.", "amount")
    return _make_advance(lead, amount, user)


def _make_advance(lead, amount, user):
    from sales.models import Invoice
    from sales.services import create_invoice

    today = timezone.localdate()
    invoice = create_invoice(
        source=Invoice.ONSITE, lead=lead, is_advance=True, party=lead.party, stock_point=lead.stock_point,
        date=today, due_date=today, status=Invoice.LINK_SENT,
        lines=[{"description": f"Advance for on-site service {lead.code}", "qty": 1, "price": amount}],
    )
    if lead.advance_amount != amount:
        lead.advance_amount = amount
        lead.save(update_fields=["advance_amount"])
    log(lead, "advance_asked", f"Advance invoice {invoice.code} raised: ₹{amount}", user)
    return invoice


def advance_received(lead):
    from sales.models import Invoice

    return sum(i.total for i in lead.invoices.filter(is_advance=True, status=Invoice.PAID).prefetch_related("items"))


def bill_invoice(lead):
    from sales.models import Invoice

    return lead.invoices.filter(is_advance=False).exclude(status=Invoice.CANCELLED).order_by("-id").first()


# ------------------------------------------------------------------- work

@transaction.atomic
def start_work(lead, user):
    lead = lock(lead)
    _require_work(user, lead)
    _state(lead, (Lead.APPROVED,), "start the work")
    lead.status = Lead.IN_WORK
    lead.work_started_at = timezone.now()
    lead.save(update_fields=["status", "work_started_at"])
    log(lead, "work_started", "Work started", user)
    return lead


def _deduct(lead, quote):
    """Cover the quoted parts and products. What the technician already carries
    for this job (issued to them earlier) is used first -- it left the shelf at
    issue time -- and only the rest is taken off the shelf at the job's store.
    Nothing is changed if the shelf is short."""
    lines = [l for l in quote.lines.filter(deducted=False).select_related("part", "variant__product")
             if l.kind in (LeadQuoteLine.PART, LeadQuoteLine.PRODUCT)]
    carried = {}
    for iss in LeadPartIssue.objects.select_for_update().filter(lead=lead):
        if iss.outstanding > 0:
            carried.setdefault(iss.key, []).append(iss)
    plan, changed = [], set()
    for line in lines:
        key = (line.kind, line.part_id or line.variant_id)
        need, from_custody = line.qty, 0
        for iss in carried.get(key, []):
            take = min(iss.outstanding, need)
            if take > 0:
                iss.qty_used += take
                changed.add(iss)
                need -= take
                from_custody += take
        plan.append((line, from_custody, need))
    # what is still needed from the shelf, per item
    shelf_need, rows = {}, {}
    for line, _, need in plan:
        if need <= 0:
            continue
        key = (line.kind, line.part_id or line.variant_id)
        shelf_need[key] = shelf_need.get(key, 0) + need
        if key not in rows:
            if line.kind == LeadQuoteLine.PART:
                rows[key] = PartStock.objects.select_for_update().filter(part=line.part, stock_point_id=lead.stock_point_id).first()
            else:
                rows[key] = Stock.objects.select_for_update().filter(variant=line.variant, stock_point_id=lead.stock_point_id).first()
    short = []
    for line, _, need in plan:
        key = (line.kind, line.part_id or line.variant_id)
        if need > 0 and shelf_need.get(key):
            have = rows[key].quantity if rows[key] else 0
            if shelf_need[key] > have:
                short.append(f"{line.description}: need {shelf_need[key]} more, have {have}")
                shelf_need[key] = 0
    if short:
        raise ValidationError({"detail": "Not enough stock at this store -- " + "; ".join(short) + "."})
    for iss in changed:
        iss.save(update_fields=["qty_used"])
    for line, from_custody, need in plan:
        if need > 0:
            row = rows[(line.kind, line.part_id or line.variant_id)]
            row.quantity -= need
            row.save(update_fields=["quantity"])
        line.deducted = True
        line.custody_qty = from_custody
        line.save(update_fields=["deducted", "custody_qty"])


@transaction.atomic
def complete_work(lead, user, notes=""):
    from sales.models import Invoice
    from sales.services import create_invoice

    lead = lock(lead)
    _require_work(user, lead)
    _state(lead, (Lead.IN_WORK,), "complete the work")
    quote = lead.quotes.filter(status=LeadQuote.APPROVED).order_by("-version").first()
    if not quote:
        raise _err("There is no approved bill for this job.")
    _deduct(lead, quote)
    today = timezone.localdate()
    lines = []
    for line in quote.lines.all():
        item = {"description": line.description, "qty": line.qty, "price": line.price}
        if line.kind == LeadQuoteLine.PRODUCT:
            item["variant"] = line.variant  # the invoice line locks the product's cost itself
        elif line.kind == LeadQuoteLine.PART:
            # lock the part's purchase cost for the profit report; no cost entered yet -> left blank
            # so the report lists it under "missing cost" instead of counting it as free
            item.update(item_kind="part", unit_cost=(line.part.cost or None) if line.part_id else None)
        lines.append(item)
    total = quote.total
    received = min(advance_received(lead), total)
    if received:
        lines.append({"description": "Less: advance received", "qty": 1, "price": -received})
    # an advance that was asked for but never paid can't be collected any more
    for adv in lead.invoices.filter(is_advance=True, status__in=Invoice.OUTSTANDING):
        adv.status, adv.cancel_reason, adv.cancelled_at, adv.cancelled_by = Invoice.CANCELLED, "Unpaid advance replaced by the final bill", timezone.now(), user
        adv.save(update_fields=["status", "cancel_reason", "cancelled_at", "cancelled_by"])
    invoice = create_invoice(
        source=Invoice.ONSITE, lead=lead, party=lead.party, stock_point=lead.stock_point, date=today,
        status=Invoice.LINK_SENT, lines=lines,
    )
    lead.status = Lead.WORK_DONE
    lead.work_done_at = timezone.now()
    lead.work_notes = (notes or "")[:2000]
    lead.save(update_fields=["status", "work_done_at", "work_notes"])
    log(lead, "work_done", f"Work completed; invoice {invoice.code} for ₹{invoice.total} raised", user)
    if invoice.total <= 0:
        invoice.status, invoice.pay_method, invoice.paid_on, invoice.settled_by = Invoice.PAID, "No charge", today, user
        invoice.save(update_fields=["status", "pay_method", "paid_on", "settled_by"])
        _check_out(lead, "Fully covered by the advance")
    return invoice


def _check_out(lead, note="Payment received"):
    lead.status = lead.status if lead.status in (Lead.REJECTED, Lead.TO_STORE) else Lead.CLOSED
    lead.checked_out_at = timezone.now()
    lead.save(update_fields=["status", "checked_out_at"])
    log(lead, "checked_out", f"Checked out -- {note}")
    flag_returns(lead)


def on_lead_invoice_paid(invoice):
    lead = Lead.objects.select_for_update().get(pk=invoice.lead_id)
    log(lead, "payment", f"{invoice.code} paid: ₹{invoice.total} via {invoice.pay_method}")
    if invoice.is_advance:
        return
    if lead.status in (Lead.WORK_DONE, Lead.REJECTED, Lead.TO_STORE) and not lead.checked_out_at:
        _check_out(lead)
    text = f"Thank you {lead.party.name}. We received ₹{invoice.total} for job {lead.code} ({invoice.code})."
    send_whatsapp(_party_phone(lead), text)


def on_lead_invoice_cancelled(invoice, user):
    """Cancelling the final bill puts the stock back and reopens the work."""
    lead = Lead.objects.select_for_update().get(pk=invoice.lead_id)
    if invoice.is_advance:
        log(lead, "advance_cancelled", f"Advance {invoice.code} cancelled", user)
        return
    if lead.status == Lead.WORK_DONE:
        quote = lead.quotes.filter(status=LeadQuote.APPROVED).order_by("-version").first()
        if quote:
            for line in quote.lines.filter(deducted=True):
                if line.kind == LeadQuoteLine.PART:
                    model, key = PartStock, {"part_id": line.part_id}
                else:
                    model, key = Stock, {"variant_id": line.variant_id}
                back_to_tech = line.custody_qty
                for iss in LeadPartIssue.objects.select_for_update().filter(lead=lead, kind=line.kind, **key).order_by("-id"):
                    give = min(iss.qty_used, back_to_tech)
                    if give:
                        iss.qty_used -= give
                        iss.save(update_fields=["qty_used"])
                        back_to_tech -= give
                shelf = line.qty - line.custody_qty + back_to_tech  # any custody that can't be handed back goes to the shelf
                if shelf and not model.objects.filter(stock_point_id=lead.stock_point_id, **key).update(quantity=models_f(shelf)):
                    model.objects.create(stock_point_id=lead.stock_point_id, quantity=shelf, **key)
                line.deducted = False
                line.custody_qty = 0
                line.save(update_fields=["deducted", "custody_qty"])
        lead.status = Lead.IN_WORK
        lead.work_done_at = None
        lead.save(update_fields=["status", "work_done_at"])
        log(lead, "invoice_cancelled", f"Bill {invoice.code} cancelled; stock restored and the job reopened", user)
    else:
        log(lead, "invoice_cancelled", f"{invoice.code} cancelled", user)


def models_f(qty):
    from django.db.models import F

    return F("quantity") + qty


# ---------------------------------------------------------- closing paths

@transaction.atomic
def close_on_credit(lead, user, reason):
    if not user.has_perm_code("leads.manage"):
        raise PermissionDenied("Only an Admin can check a job out with payment pending.")
    reason = (reason or "").strip()
    if not reason:
        raise _err("Give a reason for closing the job with payment pending.", "reason")
    lead = lock(lead)
    _state(lead, (Lead.WORK_DONE,), "close on credit")
    lead.closed_on_credit, lead.credit_reason = True, reason[:200]
    lead.save(update_fields=["closed_on_credit", "credit_reason"])
    _check_out(lead, f"payment pending -- {reason}")
    return lead


@transaction.atomic
def cancel(lead, user, reason, charge_visit=False):
    if not (user.has_perm_code("leads.manage") or can_work(user, lead) and user.has_perm_code("leads.work")):
        raise PermissionDenied("You do not have permission to cancel this job.")
    reason = (reason or "").strip()
    if not reason:
        raise _err("Give a reason for cancelling.", "reason")
    lead = lock(lead)
    _state(lead, (Lead.NEW, Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK), "cancel")
    lead.approvals.filter(status=LeadApproval.PENDING).update(status=LeadApproval.REVOKED)
    lead.status, lead.cancel_reason = Lead.CANCELLED, reason[:200]
    lead.save(update_fields=["status", "cancel_reason"])
    log(lead, "cancelled", f"Cancelled -- {reason}", user)
    flag_returns(lead)
    if charge_visit and lead.checked_in_at:
        raise_visit_invoice(lead)
    return lead


@transaction.atomic
def take_to_store(lead, user, reason, charge_visit=True):
    """The laptop can't be fixed on site: bring it to the store, where it is
    repaired as a normal Repairs ticket (handled by the in-house technician /
    repair staff, not the on-site one). An advance already received goes
    across to the ticket; one still unpaid is dropped."""
    from repairs.models import RepairTicket
    from sales.models import Invoice

    if not (user.has_perm_code("leads.manage") or (user.has_perm_code("leads.work") and can_work(user, lead))):
        raise PermissionDenied("You do not have permission to take this job to the store.")
    reason = (reason or "").strip()
    if not reason:
        raise _err("Say why it can't be fixed on site.", "reason")
    lead = lock(lead)
    _state(lead, (Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK), "take it to the store")
    lead.approvals.filter(status=LeadApproval.PENDING).update(status=LeadApproval.REVOKED)
    parts = (lead.device or "Laptop").split(None, 1)
    note = lead.issue + (f"\n\nOn-site diagnosis ({lead.code}): {lead.diagnosis}" if lead.diagnosis else "") + f"\n\nBrought to store because: {reason}"
    ticket = RepairTicket.objects.create(
        code=f"TMP-{lead.code}", party=lead.party, brand=parts[0][:40], model_name=(parts[1] if len(parts) > 1 else "—")[:80],
        stock_point=lead.stock_point, issue=note, received=timezone.localdate(), payment=RepairTicket.FULL,
    )
    ticket.code = f"RPR-{1044 + ticket.pk}"
    ticket.advance_paid = advance_received(lead)
    ticket.save(update_fields=["code", "advance_paid"])
    for adv in lead.invoices.filter(is_advance=True, status__in=Invoice.OUTSTANDING):
        adv.status, adv.cancel_reason, adv.cancelled_at, adv.cancelled_by = Invoice.CANCELLED, "Job moved to a store repair ticket", timezone.now(), user
        adv.save(update_fields=["status", "cancel_reason", "cancelled_at", "cancelled_by"])
    lead.repair_ticket = ticket
    lead.status = Lead.TO_STORE
    lead.save(update_fields=["repair_ticket", "status"])
    log(lead, "to_store", f"Taken to the store -- repair ticket {ticket.code} opened ({reason})", user)
    flag_returns(lead)
    if charge_visit:
        raise_visit_invoice(lead)
    if not lead.invoices.filter(is_advance=False, status__in=Invoice.OUTSTANDING).exists():
        lead.checked_out_at = timezone.now()
        lead.save(update_fields=["checked_out_at"])
    notify_staff("repair_ticket_created", f"On-site job {lead.code} brought to store -- {ticket.code}",
                 f"{lead.party.name}'s {lead.device or 'laptop'} could not be fixed on site and is now repair ticket {ticket.code} at {lead.stock_point.name}. {reason}")
    send_whatsapp(_party_phone(lead), f"Hello {lead.party.name}, your laptop from job {lead.code} is being repaired at our store (ticket {ticket.code}). We'll keep you posted.")
    return ticket


# ------------------------------------------------- parts in a technician's name

ISSUE_STATES = (Lead.ASSIGNED, Lead.VISITING, Lead.DIAGNOSED, Lead.AWAITING, Lead.APPROVED, Lead.IN_WORK)


def can_handle_parts(user):
    return user.has_perm_code("leads.parts")


def _require_parts(user):
    if not can_handle_parts(user):
        raise PermissionDenied("You do not have permission to issue or take back parts.")


def _shelf_row(model, lead, **key):
    return model.objects.select_for_update().filter(stock_point_id=lead.stock_point_id, **key).first()


@transaction.atomic
def issue_parts(lead, user, kind, item_id, qty, note=""):
    """Hand stock to the job's technician. It leaves the shelf now, without an
    invoice, and is carried in their name until used or returned."""
    _require_parts(user)
    lead = lock(lead)
    _state(lead, ISSUE_STATES, "issue parts for")
    if not lead.assigned_to_id:
        raise _err("Assign a technician before issuing parts.")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise _err("Enter how many to issue.", "qty")
    if not 1 <= qty <= 999:
        raise _err("Enter a quantity between 1 and 999.", "qty")
    if kind == LeadPartIssue.PART:
        item = Part.objects.filter(pk=item_id).first()
        key, model, label = {"part_id": item.pk if item else None}, PartStock, item.name if item else ""
    elif kind == LeadPartIssue.PRODUCT:
        item = Variant.objects.select_related("product").filter(pk=item_id).first()
        key, model = {"variant_id": item.pk if item else None}, Stock
        label = f"{item.product.display_name} {item.spec}".strip() if item else ""
    else:
        raise _err("Choose a spare part or a product.", "kind")
    if not item:
        raise _err("Pick the item to issue.", "item")
    row = _shelf_row(model, lead, **key)
    have = row.quantity if row else 0
    if qty > have:
        raise _err(f"Only {have} of {label} in stock at {lead.stock_point.name}.", "qty")
    row.quantity -= qty
    row.save(update_fields=["quantity"])
    issue = LeadPartIssue.objects.create(
        lead=lead, technician=lead.assigned_to, kind=kind, description=label[:160], qty_issued=qty,
        note=(note or "")[:200], issued_by=user, **key)
    log(lead, "parts_issued", f"{qty} × {label} issued to {lead.assigned_to}", user)
    return issue


@transaction.atomic
def receive_return(lead, user, issue_id, qty):
    """The technician hands unused stock back: it goes back on this store's shelf."""
    _require_parts(user)
    lead = lock(lead)
    issue = LeadPartIssue.objects.select_for_update().filter(pk=issue_id, lead=lead).first()
    if not issue:
        raise _err("That issued item was not found on this job.", "issue")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise _err("Enter how many came back.", "qty")
    if not 1 <= qty <= issue.outstanding:
        raise _err(f"{issue.technician} is holding {issue.outstanding} of this -- enter 1 to {issue.outstanding}." if issue.outstanding
                   else "Nothing is outstanding on this item.", "qty")
    key = {"part_id": issue.part_id} if issue.kind == LeadPartIssue.PART else {"variant_id": issue.variant_id}
    model = PartStock if issue.kind == LeadPartIssue.PART else Stock
    if not model.objects.filter(stock_point_id=lead.stock_point_id, **key).update(quantity=models_f(qty)):
        model.objects.create(stock_point_id=lead.stock_point_id, quantity=qty, **key)
    issue.qty_returned += qty
    issue.save(update_fields=["qty_returned"])
    log(lead, "parts_returned", f"{qty} × {issue.description} returned by {issue.technician} to {lead.stock_point.name}", user)
    return issue


@transaction.atomic
def write_off(lead, user, issue_id, qty, reason):
    """Stock the technician lost or damaged: it is not coming back, so it is
    closed out of their account (the shelf is not credited). Admin only, with a reason."""
    if not user.has_perm_code("leads.manage"):
        raise PermissionDenied("Only an Admin can write off stock.")
    reason = (reason or "").strip()
    if not reason:
        raise _err("Give the reason (lost, damaged, ...).", "reason")
    lead = lock(lead)
    issue = LeadPartIssue.objects.select_for_update().filter(pk=issue_id, lead=lead).first()
    if not issue:
        raise _err("That issued item was not found on this job.", "issue")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise _err("Enter how many to write off.", "qty")
    if not 1 <= qty <= issue.outstanding:
        raise _err("Nothing is outstanding on this item." if not issue.outstanding else f"Enter 1 to {issue.outstanding}.", "qty")
    issue.qty_written_off += qty
    issue.save(update_fields=["qty_written_off"])
    log(lead, "parts_written_off", f"{qty} × {issue.description} written off from {issue.technician} -- {reason[:150]}", user)
    return issue


def flag_returns(lead):
    """The job has ended: tell each technician to return what they still hold
    (in the bell) and tell Admins. Never raises -- it runs after the job closed."""
    try:
        from accounts.models import StaffNotification

        pending = [i for i in lead.part_issues.select_related("technician") if i.outstanding > 0 and i.alerted_at is None]
        if not pending:
            return
        now = timezone.now()
        by_tech = {}
        for i in pending:
            by_tech.setdefault(i.technician, []).append(i)
        names = []
        for tech, items in by_tech.items():
            what = ", ".join(f"{i.outstanding} × {i.description}" for i in items)
            StaffNotification.objects.create(
                user=tech, event_key="parts_return", subject=f"Return parts to the store -- {lead.code}",
                body=f"Job {lead.code} ({lead.party.name}) is closed and these were not used: {what}. "
                     f"Please hand them back at {lead.stock_point.name}.")
            names.append(f"{tech}: {what}")
        for i in pending:
            i.alerted_at = now
            i.save(update_fields=["alerted_at"])
        log(lead, "parts_due", "Unused parts to return -- " + "; ".join(names))
        notify_staff("lead_parts_due", f"Parts not yet returned -- {lead.code}",
                     f"Job {lead.code} is closed but still has stock with the technician: " + "; ".join(names) + ".")
    except Exception:
        import logging

        logging.getLogger(__name__).exception("flag_returns failed for %s", getattr(lead, "code", "?"))
