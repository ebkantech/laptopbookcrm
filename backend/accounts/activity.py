"""
Staff Activity Logs -- how actions are recorded, and who may read them.

Recording (server-side only)
----------------------------
ActivityLogMiddleware opens a scope for every write request to /api/
(POST / PUT / PATCH / DELETE). While the view runs, model signals on the
TRACKED models note what was created, updated (with a safe field diff)
or deleted, and where (its store, when the record carries one). The
existing repair / rental domain events (RepairTicketEvent, RentalEvent)
are folded into their ticket / agreement so a lifecycle step reads
"Stage changed - repair ticket RPR-1045", not two rows.

When the response is a 2xx and the requester is a signed-in staff
account, the scope is written in one bulk insert -- one row per record
touched, merged (create + later save of the same record = one "created").
Failed requests, anonymous / customer requests and work done outside a
request (management commands, webhooks) record nothing. The actor is
always request.user as authenticated by the server; nothing in the
request body can set it.

Code that changes data without model signals (QuerySet.update(), e.g. a
stock quantity) calls note() with an explicit description; it merges with
any signal event for the same record. Each row also keeps the actor's own
Store Location at that moment (actor_stock_point). Permission denials are
security events, not work: they stay in accounts.PermissionDeniedLog only.

Never stored: passwords, password hashes, tokens, OTPs, secrets, provider
ids, IPs / user agents, request headers. Personal / free-text fields are
masked -- the change is noted, not the value.

Reading (three tiers, from the existing role system -- see role_tier)
-------
Superuser: own, Admin and ordinary Staff logs (other superusers only with
  settings.ACTIVITY_LOGS_SUPERUSER_PEERS).
Admin (Owner role or roles.manage): own and ordinary Staff logs within
  their store scope; never another Admin's, never a Superuser's.
Staff: their own log only, and only work at their own Store Location.
visible_logs() narrows the entries further (completed work only, module
view permissions, privileged entries, store isolation) and every count,
search, filter and page is computed from it.
"""
import contextvars
import datetime
import decimal
import logging
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q
from django.db.models.signals import post_delete, post_save, pre_save
from django.utils import timezone

logger = logging.getLogger("accounts.activity")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Fields never written into a log, under any name.
SECRET_FIELD_RE = re.compile(r"password|token|secret|otp|hash|digest|ciphertext|signature|jti|api_?key", re.I)
SKIP_FIELDS = {
    "id", "last_login", "date_joined", "is_staff", "provider_link_id", "provider_payment_id", "url", "upi_check",
    "decided_ip", "decided_user_agent", "ip_address", "user_agent", "latitude", "longitude", "snapshot",
}
# Personal or free-text fields: "changed", never the value.
MASKED_FIELDS = {
    "phone", "email", "address", "gstin", "serial", "serial_number", "body", "text", "comment", "notes",
    "description", "terms", "issue", "reason", "particulars", "reference", "payment_reference", "condition_notes",
    "accessories", "checks", "cancel_reason", "sent_to_phone", "customer_phone", "customer_name", "audience",
    "number", "name_on_id",
}
MASKED = "(changed)"


def _fk(name):
    def get(o):
        return getattr(o, f"{name}_id", None)
    return get


def _via(path):
    """Store id through a related record, e.g. "invoice.stock_point_id"."""
    def get(o):
        cur = o
        for part in path.split("."):
            cur = getattr(cur, part, None)
            if cur is None:
                return None
        return cur
    return get


def _first(*getters):
    def get(o):
        for g in getters:
            value = g(o)
            if value:
                return value
        return None
    return get


@dataclass(frozen=True)
class Track:
    module: str
    noun: str
    label: object  # callable(instance) -> str
    store: object = None  # callable(instance) -> stock point id | None
    parent: object = None  # callable(instance) -> (record_type, id) to fold into
    domain_label: object = None  # callable(instance) -> lifecycle label


def _code(attr, fallback="#{pk}"):
    return lambda o: str(getattr(o, attr, "") or fallback.format(pk=o.pk))


TRACKED = {
    "sales.invoice": Track("sales", "invoice", _code("code"), _fk("stock_point")),
    "sales.refund": Track("payments", "refund", lambda o: f"on {o.invoice.code}", _via("invoice.stock_point_id")),
    "sales.paymentlink": Track("payments", "payment link", lambda o: f"for {o.invoice.code}", _via("invoice.stock_point_id")),
    "rentals.rental": Track("rentals", "rental agreement", _code("agreement_code")),
    "rentals.rentalasset": Track("rentals", "rental device", lambda o: o.asset_tag or f"#{o.pk}",
                                 _first(_fk("returned_to"), _fk("source_stock_point"))),
    "rentals.rentalissue": Track("rentals", "rental issue", lambda o: f"#{o.pk}"),
    "rentals.rentalevent": Track("rentals", "rental agreement", lambda o: o.rental.agreement_code or f"#{o.rental_id}",
                                 parent=lambda o: ("rentals.rental", o.rental_id),
                                 domain_label=lambda o: o.get_event_type_display()),
    "leads.lead": Track("leads", "on-site job", _code("code"), _fk("stock_point")),
    "leads.leadevent": Track("leads", "on-site job", lambda o: o.lead.code, _via("lead.stock_point_id"),
                             parent=lambda o: ("leads.lead", o.lead_id),
                             domain_label=lambda o: o.text or o.event),
    "repairs.repairticket": Track("repairs", "repair ticket", _code("code"), _fk("stock_point")),
    "repairs.repairorder": Track("repairs", "repair order", _code("code")),
    "repairs.repairreopen": Track("repairs", "repair ticket", lambda o: o.ticket.code, _via("ticket.stock_point_id"),
                                  parent=lambda o: ("repairs.repairticket", o.ticket_id),
                                  domain_label=lambda o: "Reopened"),
    "repairs.repairticketevent": Track("repairs", "repair ticket", lambda o: o.ticket.code, _via("ticket.stock_point_id"),
                                       parent=lambda o: ("repairs.repairticket", o.ticket_id),
                                       domain_label=lambda o: o.get_event_type_display()),
    "catalog.stockpoint": Track("stores", "store", lambda o: o.name, lambda o: o.pk),
    "catalog.product": Track("inventory", "product", lambda o: o.product_code),
    "catalog.variant": Track("inventory", "variant", lambda o: o.code),
    "catalog.stock": Track("inventory", "stock", lambda o: f"{o.variant.code} at {o.stock_point.name}", _fk("stock_point")),
    "parties.party": Track("parties", "customer", lambda o: o.name),
    "parties.message": Track("parties", "message", lambda o: f"to {o.party.name}"),
    "portal.portalinvite": Track("parties", "portal invite", lambda o: f"for {o.party.name}"),
    "accounting.cashentry": Track("accounting", "cash entry", lambda o: f"#{o.pk}",
                                  _first(_via("invoice.stock_point_id"), _via("refund.invoice.stock_point_id"),
                                         _via("expense_payment.expense.stock_point_id"), _via("expense_reversal.expense.stock_point_id"))),
    "accounting.bankentry": Track("accounting", "bank entry", lambda o: f"#{o.pk}",
                                  _first(_via("invoice.stock_point_id"), _via("refund.invoice.stock_point_id"),
                                         _via("expense_payment.expense.stock_point_id"), _via("expense_reversal.expense.stock_point_id"))),
    "accounting.expense": Track("accounting", "expense", lambda o: o.code, _fk("stock_point")),
    "accounting.expensepayment": Track("accounting", "expense", lambda o: o.expense.code, _via("expense.stock_point_id"),
                                       parent=lambda o: ("accounting.expense", o.expense_id),
                                       domain_label=lambda o: f"Payment of Rs {o.amount} recorded ({o.method})"),
    "accounting.expenseattachment": Track("accounting", "expense", lambda o: o.expense.code, _via("expense.stock_point_id"),
                                          parent=lambda o: ("accounting.expense", o.expense_id),
                                          domain_label=lambda o: "Attachment added"),
    "accounting.bankaccount": Track("accounting", "bank account", lambda o: o.name),
    "warranty.warranty": Track("warranty", "warranty", lambda o: o.item_label,
                               _first(_via("invoice.stock_point_id"), _via("repair_ticket.stock_point_id"))),
    "broadcast.campaign": Track("broadcast", "campaign", lambda o: o.title),
    "broadcast.whatsapporder": Track("broadcast", "WhatsApp order", lambda o: f"#{o.pk}"),
    "accounts.user": Track("staff", "staff account", lambda o: o.username, _fk("stock_point")),
    "accounts.role": Track("staff", "role", lambda o: o.label),
    "accounts.notificationrule": Track("staff", "staff alert rule", lambda o: o.get_event_key_display()),
}

# Past-tense wording for custom API actions (DRF url_name suffix).
ACTION_TEXT = {
    "settle": "Settled {target}", "refund": "Refunded {target}", "cancel": "Cancelled {target}",
    "upi-check": "Checked UPI payment for {target}", "send-upi-link": "Sent a UPI payment link for {target}",
    "refresh-payment": "Refreshed payment status of {target}", "simulate-payment": "Simulated a payment for {target}",
    "create-agreement": "Created {target}", "approval-link": "Created a customer approval link for {target}",
    "approval-link-send-whatsapp": "Sent the approval link on WhatsApp for {target}",
    "assign": "Assigned {target}", "resolve": "Resolved {target}", "retry": "Retried sending {target}",
    "send-message": "Sent a message for {target}", "quote": "Sent a quote for {target}",
    "approve-on-behalf": "Approved {target} on the customer's behalf", "close": "Closed {target}",
    "raise-invoice": "Raised a rent invoice for {target}", "from-inventory": "Rented out from inventory as {target}",
    "return-to-inventory": "Returned {target} to inventory", "finalize-estimate": "Finalized the estimate for {target}",
    "advance": "Recorded the advance for {target}", "set-stage": "Changed the stage of {target}",
    "reopen": "Reopened {target}", "set-status": "Changed the status of {target}",
    "set-active": "Changed sign-in access of {target}", "reset-password": "Issued a password reset for {target}",
    "set-store": "Changed the Store Location of {target}", "set-role": "Changed the role of {target}",
    "change-password": "Changed their own password", "portal-invite": "Sent a portal invite for {target}",
    "portal-reset-link": "Sent a portal reset link for {target}", "recheck-whatsapp": "Re-checked WhatsApp for {target}",
    "revoke-portal-access": "Revoked portal access for {target}", "message": "Sent a message for {target}",
    "toggle-reconciled": "Changed reconciliation of {target}", "payments": "Recorded a payment on {target}",
    "attachments": "Added attachments to {target}", "attachment-removed": "Removed an attachment from {target}", "delete-for-everyone": "Deleted {target} for everyone",
    "add-stock": "Added stock: {target}", "stock-location": "Changed the bin location of {target}",
}
KIND_TEXT = {"created": "Created {target}", "updated": "Updated {target}", "deleted": "Deleted {target}"}

# Permission needed to read each module's entries (any one of them). An
# empty tuple: readable by every log viewer (catalogue / stores are shared).
MODULE_PERMS = {
    "sales": ("invoices.view",), "payments": ("invoices.view",), "rentals": ("rentals.view",),
    "repairs": ("repairs.view",), "leads": ("leads.view",), "parties": ("parties.view",), "accounting": ("cashbook.view", "bankbook.view"),
    "broadcast": ("broadcast.send", "orders.manage"), "inventory": (), "stores": (), "warranty": (),
    "staff": ("roles.manage",),
}
MODULE_LABELS = {
    "sales": "Sales", "payments": "Payments", "rentals": "Rentals", "repairs": "Repairs", "leads": "On-site service", "inventory": "Inventory",
    "parties": "Customers", "accounting": "Accounting", "warranty": "Warranty", "broadcast": "Broadcast",
    "stores": "Store Management", "staff": "Staff Management",
}

# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------

@dataclass
class _Event:
    record_type: str
    record_id: str
    track: Track
    kind: str  # created / updated / deleted / event
    label: str = ""
    store_id: object = None
    changes: dict = field(default_factory=dict)
    domain_label: str = ""
    action: str = ""
    description: str = ""


class _Scope:
    def __init__(self):
        self.events = {}  # (record_type, id) -> _Event
        self.before = {}  # (record_type, id) -> {attname: value}

    def add(self, ev):
        key = (ev.record_type, ev.record_id)
        cur = self.events.get(key)
        if cur is None:
            self.events[key] = ev
            return
        # one row per record per request: created/deleted win over updated,
        # explicit wording and domain labels win over generic ones
        if ev.kind in ("created", "deleted") or cur.kind == "event":
            cur.kind = ev.kind if ev.kind != "event" else cur.kind
        for k, (before, after) in ev.changes.items():
            cur.changes[k] = [cur.changes[k][0], after] if k in cur.changes else [before, after]
        cur.label = ev.label or cur.label
        cur.store_id = ev.store_id or cur.store_id
        cur.domain_label = ev.domain_label or cur.domain_label
        cur.action = ev.action or cur.action
        cur.description = ev.description or cur.description


_scope = contextvars.ContextVar("activity_scope", default=None)


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:  # a label must never break the business operation
        return None


def _json(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return str(value)[:120]


def _loggable_fields(model):
    for f in model._meta.concrete_fields:
        if f.name in SKIP_FIELDS or SECRET_FIELD_RE.search(f.name):
            continue
        if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
            continue
        yield f


def _on_pre_save(sender, instance, raw=False, update_fields=None, **kwargs):
    scope = _scope.get()
    if scope is None or raw or instance.pk is None or instance._state.adding:
        return
    label = sender._meta.label_lower
    track = TRACKED.get(label)
    if track is None or track.parent:
        return
    names = [f.attname for f in _loggable_fields(sender)
             if update_fields is None or f.name in update_fields or f.attname in update_fields]
    if names and (label, str(instance.pk)) not in scope.before:
        row = sender._base_manager.filter(pk=instance.pk).values(*names).first()
        if row is not None:
            scope.before[(label, str(instance.pk))] = row


def _display(f, value):
    if f.is_relation and value is not None:
        obj = _safe(lambda: f.related_model._base_manager.filter(pk=value).first())
        return str(obj)[:120] if obj is not None else f"#{value}"
    if f.choices:
        return dict(f.flatchoices).get(value, value)
    return _json(value)


def _diff(sender, instance, before):
    changes = {}
    for f in _loggable_fields(sender):
        if f.attname not in before:
            continue
        old, new = before[f.attname], getattr(instance, f.attname)
        if old == new:
            continue
        if f.name in MASKED_FIELDS:
            changes[f.name] = [MASKED, MASKED]
        else:
            changes[f.name] = [_display(f, old), _display(f, new)]
    return changes


def _on_post_save(sender, instance, created=False, raw=False, **kwargs):
    scope = _scope.get()
    if scope is None or raw:
        return
    label = sender._meta.label_lower
    track = TRACKED.get(label)
    if track is None:
        return
    if track.parent:
        if not created:
            return
        parent = _safe(track.parent, instance)
        if not parent or parent[1] is None:
            return
        scope.add(_Event(parent[0], str(parent[1]), track, "event", label=_safe(track.label, instance) or "",
                         store_id=_safe(track.store, instance) if track.store else None,
                         domain_label=_safe(track.domain_label, instance) or ""))
        return
    key = (label, str(instance.pk))
    changes = {} if created else _diff(sender, instance, scope.before.pop(key, {}))
    scope.add(_Event(label, str(instance.pk), track, "created" if created else "updated",
                     label=_safe(track.label, instance) or f"#{instance.pk}",
                     store_id=_safe(track.store, instance) if track.store else None, changes=changes))


def _on_post_delete(sender, instance, **kwargs):
    scope = _scope.get()
    if scope is None:
        return
    label = sender._meta.label_lower
    track = TRACKED.get(label)
    if track is None or track.parent:
        return
    scope.add(_Event(label, str(instance.pk), track, "deleted", label=_safe(track.label, instance) or f"#{instance.pk}",
                     store_id=_safe(track.store, instance) if track.store else None))


def connect_signals():
    pre_save.connect(_on_pre_save, dispatch_uid="activity_pre_save")
    post_save.connect(_on_post_save, dispatch_uid="activity_post_save")
    post_delete.connect(_on_post_delete, dispatch_uid="activity_post_delete")


def note(instance, action, description, *, changes=None, store_id=None):
    """Explicitly describe what happened to `instance` in this request (for
    changes model signals can't see, like QuerySet.update()). Merges with
    any signal event for the same record. No-op outside a write request."""
    scope = _scope.get()
    if scope is None:
        return
    label = instance._meta.label_lower
    track = TRACKED.get(label)
    if track is None:
        return
    scope.add(_Event(label, str(instance.pk), track, "updated", label=_safe(track.label, instance) or "",
                     store_id=store_id if store_id is not None else (_safe(track.store, instance) if track.store else None),
                     changes={k: [_json(a), _json(b)] for k, (a, b) in (changes or {}).items()},
                     action=action, description=description))


def _view_model(request):
    match = getattr(request, "resolver_match", None)
    cls = getattr(getattr(match, "func", None), "cls", None)
    qs = getattr(cls, "queryset", None)
    return getattr(getattr(qs, "model", None), "_meta", None), match


def _url_action(match, method):
    """The custom action this request ran ("settle", "set-stage", ...), or ""
    for plain create / update / delete. ViewSets say it exactly; a plain
    APIView is named by its URL (e.g. "add-stock")."""
    func = getattr(match, "func", None)
    actions = getattr(func, "actions", None)
    if actions is not None:
        name = actions.get(method.lower(), "")
        return "" if name in ("create", "update", "partial_update", "destroy") else name.replace("_", "-")
    return getattr(match, "url_name", "") or ""


def _describe(ev, primary, action):
    target = f"{ev.track.noun} {ev.label}".strip()
    if ev.description:
        return ev.description[:300]
    if ev.domain_label:
        text = f"{ev.domain_label} - {target}"
    elif primary and action:
        text = ACTION_TEXT.get(action, action.replace("-", " ").capitalize() + " - {target}").format(target=target)
    else:
        text = KIND_TEXT.get(ev.kind, "Updated {target}").format(target=target)
    return text[:300]


def _flush(scope, request, response):
    from .models import ActivityLog

    user = getattr(request, "user", None)
    if not scope.events or not (user and user.is_authenticated) or hasattr(user, "customer_profile"):
        return
    meta, match = _view_model(request)
    action = _url_action(match, request.method)
    pk = str((getattr(match, "kwargs", None) or {}).get("pk", "") or "")
    now = timezone.now()
    endpoint = f"{request.method} {request.path}"[:200]
    rows = []
    for ev in scope.events.values():
        # the record the endpoint is about: the ViewSet's own record (that id,
        # if the URL has one); a single-purpose APIView has no model, so all
        primary = meta is None or (ev.record_type == meta.label_lower and (not pk or pk == ev.record_id))
        if ev.kind == "updated" and not ev.changes and not ev.description and not ev.domain_label and not (primary and action):
            continue  # a save that changed nothing loggable
        rows.append(ActivityLog(
            actor=user, actor_privileged=bool(user.is_superuser), actor_stock_point_id=user.stock_point_id,
            at=now, module=ev.track.module,
            action=(ev.action or (action if primary and action else "") or ev.kind)[:40],
            description=_describe(ev, primary, action), record_type=ev.record_type, record_id=ev.record_id[:40],
            record_label=(ev.label or "")[:120], stock_point_id=ev.store_id, changes=ev.changes, endpoint=endpoint,
        ))
    if rows:
        ActivityLog.objects.bulk_create(rows)


class ActivityLogMiddleware:
    """Opens the per-request recording scope for API writes (see module doc)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in UNSAFE_METHODS or not request.path.startswith("/api/"):
            return self.get_response(request)
        scope = _Scope()
        token = _scope.set(scope)
        try:
            response = self.get_response(request)
        finally:
            _scope.reset(token)
        if 200 <= getattr(response, "status_code", 500) < 300:
            try:
                _flush(scope, request, response)
            except Exception:
                # the business operation already succeeded -- never fail it over its log line
                logger.exception("activity log write failed for %s %s", request.method, request.path)
        return response



# Permission denials are NOT work: they stay in accounts.PermissionDeniedLog
# (the security audit, written by accounts.permissions.HasPerm) and never
# enter this timeline. Denial rows copied here by migration 0008 are kept
# untouched but filtered out of every read below (outcome != success).


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

SUPERUSER, ADMIN, STAFF = "superuser", "admin", "staff"


def role_tier(user):
    """Superuser (is_superuser), Admin (accounts.staff.is_staff_admin -- the
    Owner role or roles.manage) or ordinary Staff. is_staff plays no part."""
    from .staff import is_staff_admin
    if user.is_superuser:
        return SUPERUSER
    return ADMIN if is_staff_admin(user) else STAFF


def _staff_account(user):
    return bool(user and user.is_authenticated and not hasattr(user, "customer_profile"))


def can_view_own_logs(viewer):
    """Any signed-in staff account may open its own work timeline."""
    return _staff_account(viewer)


def can_view_staff_logs(viewer):
    """May open OTHER people's logs: Superusers and Admins only."""
    return _staff_account(viewer) and role_tier(viewer) in (SUPERUSER, ADMIN)


def can_view_logs_of(viewer, target):
    """
    Target-level rule (UserViewSet.activity applies the store-scoped user
    lookup first):
      Superuser -> self, Admins, ordinary Staff; another Superuser only if
                   settings.ACTIVITY_LOGS_SUPERUSER_PEERS.
      Admin     -> self and ordinary Staff; never another Admin (Owner-role
                   accounts included) and never a Superuser.
      Staff     -> self only.
    """
    if not _staff_account(viewer):
        return False
    if target.pk == viewer.pk:
        return True
    viewer_tier, target_tier = role_tier(viewer), role_tier(target)
    if viewer_tier == STAFF:
        return False
    if target_tier == SUPERUSER:
        return viewer_tier == SUPERUSER and getattr(settings, "ACTIVITY_LOGS_SUPERUSER_PEERS", False)
    if viewer_tier == ADMIN:
        return target_tier == STAFF
    return True


def viewer_modules(viewer):
    if viewer.is_superuser:
        return list(MODULE_PERMS)
    return [m for m, perms in MODULE_PERMS.items() if not perms or any(viewer.has_perm_code(p) for p in perms)]


def visible_logs(viewer, target):
    """
    The eligible work timeline of `target` for `viewer` (call
    can_view_logs_of first). Every count, filter, search and page is taken
    from this queryset, so nothing outside it can surface:
      - completed work only (no permission denials);
      - modules the viewer may read anyway (existing view permissions);
      - entries made while the actor was a superuser: superusers only
        (their own, or peers when ACTIVITY_LOGS_SUPERUSER_PEERS);
      - a store-scoped viewer (Admin at one store, or Staff reading their
        own log) sees an entry only if its record belongs to that store, or
        it has no store and was done while the actor worked at that store.
        No Store Location -> nothing. Older rows whose store can't be told
        stay out rather than being guessed in.
    """
    from .models import ActivityLog
    from .store_scope import StoreScope

    qs = ActivityLog.objects.filter(actor=target, outcome=ActivityLog.SUCCESS, module__in=viewer_modules(viewer))
    peers = getattr(settings, "ACTIVITY_LOGS_SUPERUSER_PEERS", False)
    if not viewer.is_superuser or (target.pk != viewer.pk and not peers):
        qs = qs.filter(actor_privileged=False)
    scope = StoreScope(viewer)
    if not scope.all:
        if scope.store_id is None:
            return qs.none()
        qs = qs.filter(Q(stock_point_id=scope.store_id) | Q(stock_point__isnull=True, actor_stock_point_id=scope.store_id))
    return qs
