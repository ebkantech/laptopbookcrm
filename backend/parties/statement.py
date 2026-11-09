"""
A customer's statement: invoices in date order with their items, quantity,
what was paid (advances and part payments included), what is still owed on
each, and the running balance. The screen and the PDF use the same rows.
"""
from datetime import date

from django.utils import timezone

from accounts.store_scope import StoreScope
from sales.models import Invoice, InvoiceItem

KINDS = {"sale": "Sale", "repair": "Repair", "rental": "Rent", "onsite": "On-site service"}


class FilterError(ValueError):
    pass


def kind(invoice):
    if invoice.is_deposit:
        return "Security deposit"
    if invoice.is_advance:
        return "Advance"
    return KINDS.get(invoice.source, invoice.source)


def _item_name(item):
    if item.description:
        return item.description
    return item.variant.product.display_name if item.variant_id else "Item"


def parse_filters(params):
    """from / to (YYYY-MM-DD) and due=1 from the query string."""
    found = {}
    for key in ("from", "to"):
        value = params.get(key)
        if value:
            try:
                found[key] = date.fromisoformat(value)
            except ValueError:
                raise FilterError(f"{key} must be a date (YYYY-MM-DD).")
    if found.get("from") and found.get("to") and found["from"] > found["to"]:
        raise FilterError("The start date is after the end date.")
    return found.get("from"), found.get("to"), params.get("due") in ("1", "true")


def build(party, user, date_from=None, date_to=None, due_only=False):
    invoices = (
        StoreScope(user).filter(Invoice.objects.filter(party=party), "stock_point")
        .exclude(status=Invoice.CANCELLED)
        .prefetch_related("items__variant__product", "part_payments", "refunds")
        .order_by("date", "id")
    )
    # Whatever is still owed on invoices before the period is carried in as the opening balance.
    opening = sum(inv.balance_due for inv in invoices if date_from and inv.date < date_from)
    rows, running = [], opening
    for invoice in invoices:
        if (date_from and invoice.date < date_from) or (date_to and invoice.date > date_to):
            continue
        owed = invoice.balance_due
        if due_only and owed <= 0:
            continue
        running += owed
        goods = [item for item in invoice.items.all() if item.item_kind != InvoiceItem.DISCOUNT]
        rows.append({
            "id": invoice.id, "code": invoice.code, "date": invoice.date, "status": invoice.status,
            "kind": kind(invoice), "qty": sum(item.qty for item in goods),
            "items": [{"name": _item_name(item), "qty": item.qty} for item in goods],
            "amount": invoice.total, "paid": invoice.amount_paid, "credit": owed, "balance": running,
            "refunded": invoice.refunded_total,
            "payments": [
                {"amount": p.amount, "pay_method": p.pay_method, "paid_on": p.paid_on}
                for p in invoice.part_payments.all()
            ],
        })
    return {
        "party": {"id": party.id, "name": party.name, "phone": party.phone, "gstin": party.gstin, "city": party.city},
        "filters": {"from": date_from, "to": date_to, "due": due_only},
        "opening": opening,
        "rows": rows,
        "totals": {
            "qty": sum(r["qty"] for r in rows), "amount": sum(r["amount"] for r in rows),
            "paid": sum(r["paid"] for r in rows), "credit": sum(r["credit"] for r in rows), "balance": running,
        },
        "generated_on": timezone.localdate(),
    }


def render_pdf(data):
    """The statement as A4 PDF bytes."""
    from io import BytesIO
    from xml.sax.saxutils import escape

    from branding import texts
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from sales.documents import _date, _money

    styles = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=styles["Normal"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))
    party, f = data["party"], data["filters"]
    period = "All dates"
    if f["from"] or f["to"]:
        period = f"{_date(f['from']) if f['from'] else 'Start'} to {_date(f['to']) if f['to'] else _date(data['generated_on'])}"
    details = " · ".join(x for x in [party["phone"], party["city"], party["gstin"] and f"GSTIN {party['gstin']}"] if x)
    story = [
        Paragraph(f"<b>{escape(texts.business().name)}</b>", body),
        Paragraph("<font size=14><b>Customer statement</b></font>", body), Spacer(1, 3 * mm),
        Paragraph(f"<b>{escape(party['name'])}</b>" + (f" · {escape(details)}" if details else ""), body),
        Paragraph(escape(f"{period}{' · due invoices only' if f['due'] else ''} · as on {_date(data['generated_on'])}"), small),
        Spacer(1, 4 * mm),
    ]
    table = [["Invoice", "Items", "Qty", "Amount", "Paid / advance", "Credit", "Balance"]]
    if data["opening"]:
        table.append([Paragraph("Opening balance", body), "", "", "", "", "", _money(data["opening"])])
    for r in data["rows"]:
        notes = [f"{_date(r['date'])} · {r['kind']}"] + [
            f"Part paid {_money(p['amount'])} · {p['pay_method']} · {_date(p['paid_on'])}" for p in r["payments"]]
        items = "<br/>".join(escape(f"{i['name']} × {i['qty']}") for i in r["items"]) or "-"
        table.append([
            [Paragraph(f"<b>{escape(r['code'])}</b>", body), Paragraph("<br/>".join(escape(n) for n in notes), small)],
            Paragraph(items, body), str(r["qty"]), _money(r["amount"]), _money(r["paid"]), _money(r["credit"]),
            _money(r["balance"]),
        ])
    if not data["rows"]:
        table.append([Paragraph("No invoices for this selection.", body), "", "", "", "", "", ""])
    t = data["totals"]
    table.append(["Total", "", str(t["qty"]), _money(t["amount"]), _money(t["paid"]), _money(t["credit"]), _money(t["balance"])])
    grid = Table(table, colWidths=[36 * mm, 52 * mm, 10 * mm, 22 * mm, 22 * mm, 20 * mm, 22 * mm], repeatRows=1)
    grid.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#CCCCCC")),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(grid)
    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                      bottomMargin=12 * mm, title=f"Statement - {party['name']}").build(story)
    return buffer.getvalue()
