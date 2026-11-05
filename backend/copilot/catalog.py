"""
What the copilot may read, and the changes it may prepare.

READS is an allowlist of list/detail endpoints -- anything not matched here
(sign-in, staff accounts, activity logs, portal codes, customer ID documents,
uploaded files) is never fetched. ACTIONS is the set of changes it can prepare;
adding one here is the only way to give it a new ability, and each one still
runs through the CRM's own endpoint after a person confirms it.
"""
import re

_ID = r"\d+"
READS = [re.compile(f"^{p}$") for p in (
    "/parties/", f"/parties/{_ID}/", f"/parties/{_ID}/portal-account/",
    "/invoices/", f"/invoices/{_ID}/",
    "/tickets/", f"/tickets/{_ID}/", "/tickets/staff/", "/repair-orders/", f"/repair-orders/{_ID}/",
    "/rentals/", f"/rentals/{_ID}/", "/rentals/payment-ledger/", "/rental-assets/", f"/rental-assets/{_ID}/",
    "/rental-issues/", f"/rental-issues/{_ID}/",
    "/leads/", f"/leads/{_ID}/", "/leads/parts_due/", "/leads/technicians/",
    "/products/", f"/products/{_ID}/", f"/products/{_ID}/serials/", "/products/lookup/", "/products/low-stock/", "/parts/", "/services/",
    "/stock-points/", "/stock-points/summary/", "/stock-serials/available/", "/stock-serials/trace/",
    "/warranties/", f"/warranties/{_ID}/", "/warranties/expiring/", "/warranties/summary/", "/warranty-claims/",
    "/cash-entries/", "/bank-accounts/", "/bank-entries/", "/expenses/", f"/expenses/{_ID}/",
    "/whatsapp-orders/", f"/whatsapp-orders/{_ID}/", "/my-notifications/", "/dashboard/summary/",
    "/reports/financial-summary/", "/reports/sales-summary/", "/reports/rental-portfolio/",
    "/reports/repair-turnaround/", "/reports/party-report/", "/reports/profit-loss/", "/reports/inventory-stock/",
)]

READ_GUIDE = """Paths you can read (ids are numbers; add filters through `query`):
/parties/?q=name, /parties/<id>/ (profile, invoices, message thread)
/invoices/?status=Overdue|Paid|Payment link sent&party=<id>&source=sale|repair|rental|onsite, /invoices/<id>/
/tickets/?status=Received|Diagnosing|In Progress|Ready|Delivered&mine=1, /tickets/<id>/, /tickets/staff/, /repair-orders/
/rentals/, /rentals/<id>/, /rentals/payment-ledger/, /rental-assets/, /rental-issues/?status=
/leads/, /leads/<id>/, /leads/parts_due/, /leads/technicians/
/products/, /products/lookup/, /products/low-stock/, /parts/, /services/, /stock-points/summary/, /stock-serials/trace/?serial=
/warranties/, /warranties/expiring/, /warranties/summary/, /warranty-claims/
/cash-entries/, /bank-accounts/, /bank-entries/, /expenses/, /whatsapp-orders/, /my-notifications/, /dashboard/summary/
/reports/financial-summary/, /reports/sales-summary/, /reports/rental-portfolio/, /reports/repair-turnaround/,
/reports/party-report/, /reports/profit-loss/, /reports/inventory-stock/"""


def read_allowed(path):
    return any(pattern.match(path) for pattern in READS)


class Action:
    def __init__(self, key, label, perm, method, path, about, ids=(), required=(), optional=(), describe=None):
        self.key, self.label, self.perm, self.method, self.path = key, label, perm, method, path
        self.about = about
        self.ids = ids            # URL parameters, always whole numbers
        self.required = required  # body fields that must be present
        self.optional = optional  # other body fields that are allowed; anything else is dropped
        # (GET path with the same ids, how to name the record on the confirm
        # card, (field, expected value) read back after the change or None)
        self.describe = describe


def _party(data):
    return f"{data.get('name')} ({data.get('type')})"


def _invoice(data):
    return f"{data.get('code')} - {data.get('party_name') or ''} - Rs {data.get('total')} - {data.get('status')}"


def _ticket(data):
    return f"{data.get('code')} - {data.get('brand')} {data.get('model_name')} - {data.get('status')}"


def _code(data):
    return str(data.get("code") or data.get("title") or data.get("id"))


def _entry(data):
    return f"{data.get('date')} - {data.get('particulars') or data.get('description') or ''} - Rs {data.get('amount')}"


ACTIONS = {a.key: a for a in [
    Action("send_message", "Send a message to the customer", "parties.manage", "POST", "/parties/{party}/messages/",
           "Send one WhatsApp or email message to a customer's number/address on file. channel: whatsapp|email.",
           ids=("party",), required=("channel", "body"), describe=("/parties/{party}/", _party, None)),
    Action("create_party", "Add a customer", "parties.manage", "POST", "/parties/",
           "Create a customer. type: Retail|Dealer|Rental. All five fields are required.",
           required=("name", "type", "phone", "email", "city")),
    Action("update_party", "Update customer details", "parties.edit", "PATCH", "/parties/{party}/",
           "Correct a customer's phone, email, city or GSTIN.",
           ids=("party",), optional=("phone", "email", "city", "gstin"), describe=("/parties/{party}/", _party, None)),
    Action("settle_invoice", "Mark invoice as paid", "invoices.settle", "POST", "/invoices/{invoice}/settle/",
           "Record a payment already received. pay_method: Cash|UPI|Bank transfer|Card|Cheque|Other. payment_reference is "
           "required except for Cash. Never guess a reference: ask the user. paid_on is YYYY-MM-DD.",
           ids=("invoice",), required=("pay_method",), optional=("payment_reference", "paid_on"),
           describe=("/invoices/{invoice}/", _invoice, ("status", "Paid"))),
    Action("cancel_invoice", "Cancel invoice", "invoices.create", "POST", "/invoices/{invoice}/cancel/",
           "Cancel an unpaid invoice raised by mistake; a reason is required.",
           ids=("invoice",), required=("reason",), describe=("/invoices/{invoice}/", _invoice, ("status", "Cancelled"))),
    Action("send_upi_link", "Send UPI payment link", "payments.send_link", "POST", "/invoices/{invoice}/send-upi-link/",
           "Send a UPI payment link for an unpaid invoice to the customer's number on file. Set staff_confirmed_upi to true "
           "only if the user says they confirmed UPI with the customer.",
           ids=("invoice",), optional=("staff_confirmed_upi",), describe=("/invoices/{invoice}/", _invoice, None)),
    Action("advance_ticket", "Move repair to next stage", "repairs.manage", "POST", "/tickets/{ticket}/advance/",
           "Move a repair ticket to its next stage.", ids=("ticket",), describe=("/tickets/{ticket}/", _ticket, None)),
    Action("set_ticket_stage", "Change repair stage", "repairs.manage", "POST", "/tickets/{ticket}/set-stage/",
           "Move a repair ticket to a chosen stage. status: Received|Diagnosing|In Progress|Ready.",
           ids=("ticket",), required=("status",), optional=("override_reason",), describe=("/tickets/{ticket}/", _ticket, None)),
    Action("assign_ticket", "Assign repair to staff", "repairs.assign", "POST", "/tickets/{ticket}/assign/",
           "Give a repair ticket to a staff member. assigned_to is a user id from /tickets/staff/.",
           ids=("ticket",), required=("assigned_to",), describe=("/tickets/{ticket}/", _ticket, None)),
    Action("resolve_rental_issue", "Resolve rental issue", "rentals.manage", "POST", "/rental-issues/{issue}/resolve/",
           "Mark a reported rental issue as resolved.", ids=("issue",), describe=("/rental-issues/{issue}/", _code, ("status", "Resolved"))),
    Action("assign_rental_issue", "Assign rental issue", "rentals.manage", "POST", "/rental-issues/{issue}/assign/",
           "Give a rental issue to a staff member (assigned_to is a user id).",
           ids=("issue",), required=("assigned_to",), describe=("/rental-issues/{issue}/", _code, None)),
    Action("remind_warranty", "Send warranty reminder", "warranty.manage", "POST", "/warranties/{warranty}/remind/",
           "Send the customer the 'warranty ending' reminder now.", ids=("warranty",), describe=("/warranties/{warranty}/", _code, None)),
    Action("add_cash_entry", "Add cash book entry", "cashbook.edit", "POST", "/cash-entries/",
           "Add a manual cash book line. date YYYY-MM-DD; type: in|out as shown by /cash-entries/; amount in rupees.",
           required=("date", "particulars", "type", "amount")),
    Action("toggle_reconciled", "Change bank reconciliation", "bankbook.reconcile", "POST", "/bank-entries/{entry}/toggle-reconciled/",
           "Mark a bank entry reconciled, or undo that.", ids=("entry",), describe=("/bank-entries/{entry}/", _entry, None)),
]}


def available(user):
    return [a for a in ACTIONS.values() if user.is_superuser or user.has_perm_code(a.perm)]


ROLE_GUIDE = {
    "owner": "This is the Owner. Lead with what needs a decision across stores: overdue money, stuck repairs, stock and profit.",
    "manager": "This is an Admin. Focus on their store's approvals, unassigned repairs, overdue invoices and team workload.",
    "sales": "This is sales staff. Focus on customers, quotes, invoices, payment follow-ups and rentals.",
    "repair_staff": "This is repair staff. Focus on their assigned tickets, stages, parts and warranty. They do not handle payments.",
    "accountant": "This is accounts staff. Focus on invoices, settlements, the cash and bank books, reconciliation and expenses.",
    "auditor": "This is an Auditor. They have read-only access: answer questions and never suggest a change.",
}
SUGGESTIONS = {
    "owner": ["What needs my attention today?", "Show overdue invoices across stores", "Which repairs are stuck?"],
    "manager": ["What needs my attention today?", "Which repairs are unassigned?", "Show overdue invoices"],
    "sales": ["Which customers owe us money?", "Show today's unanswered customers", "What's low on stock?"],
    "repair_staff": ["What are my jobs today?", "Which tickets are ready for pickup?", "Which warranties end soon?"],
    "accountant": ["Show overdue invoices", "Which bank entries aren't reconciled?", "Summarise this month's sales"],
    "auditor": ["Summarise this month's sales", "Show overdue invoices", "Show cash book entries"],
}
DEFAULT_SUGGESTIONS = ["What needs my attention today?", "Find a customer", "Show overdue invoices"]
