"""
The printable invoice document -- one builder for every place an
invoice is shown as a paper/PDF document: the staff print view
(InvoiceViewSet.print_data, rendered by the CRM's PrintableInvoice.jsx)
and the customer portal PDF download (render_invoice_pdf below). Both
show the same seller, buyer, lines and totals.
"""
from io import BytesIO

from django.conf import settings
from django.utils import timezone

CURRENCY = "INR"


def invoice_document(invoice):
    from .serializers import InvoiceSerializer

    sp, party = invoice.stock_point, invoice.party
    items = []
    for n, item in enumerate(invoice.items.all(), start=1):
        variant = item.variant
        items.append({
            "n": n,
            "description": item.description or variant.product.display_name,
            "spec": variant.spec if variant else "",
            "code": variant.code if variant else "",
            "hsn": variant.product.hsn if variant else "",
            "qty": item.qty,
            "rate": item.price,
            "amount": item.qty * item.price,
        })
    serialized = InvoiceSerializer(invoice).data
    return {
        "invoice": serialized,
        "reference": serialized["reference"],
        "seller": {
            "name": settings.BUSINESS_NAME,
            "branch": sp.name,
            "address": sp.address,
            "phone": sp.phone or settings.BUSINESS_PHONE,
            "email": settings.BUSINESS_EMAIL,
            "gstin": sp.gstin or settings.BUSINESS_GSTIN,
        },
        "buyer": {
            "name": party.name, "phone": party.phone, "email": party.email,
            "gstin": party.gstin, "city": party.city,
        },
        "items": items,
        "total_qty": sum(i["qty"] for i in items),
        "total": sum(i["amount"] for i in items),
    }


def pdf_available(invoice):
    """A document can only be produced for an invoice that has lines -- never an empty/made-up one."""
    items = getattr(invoice, "_prefetched_objects_cache", {}).get("items")
    return bool(items) if items is not None else invoice.items.exists()


def _money(value):
    sign = "-" if value < 0 else ""
    return f"{sign}Rs {abs(value):,}"


def _date(value):
    if not value:
        return "-"
    if isinstance(value, str):
        from datetime import date
        value = date.fromisoformat(value[:10])
    return value.strftime("%d %b %Y")


def render_invoice_pdf(invoice):
    """The invoice document as PDF bytes (A4), from the same data the CRM prints."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    data = invoice_document(invoice)
    inv, seller, buyer = data["invoice"], data["seller"], data["buyer"]
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("right", parent=body, alignment=2)
    p = lambda text, style=body: Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    seller_lines = [f"<b>{escape(seller['name'])}</b>", escape(seller["branch"] or "")]
    if seller["address"]:
        seller_lines.append(escape(seller["address"]).replace("\n", "<br/>"))
    contact = " · ".join(x for x in [seller["phone"] and f"Ph: {seller['phone']}", seller["email"]] if x)
    if contact:
        seller_lines.append(escape(contact))
    if seller["gstin"]:
        seller_lines.append(f"GSTIN: <b>{escape(seller['gstin'])}</b>")
    head = Table([[
        Paragraph("<br/>".join(seller_lines), body),
        Paragraph(f"<font size=14><b>INVOICE</b></font><br/>No. <b>{escape(inv['code'])}</b><br/>"
                  f"Date: {_date(inv['date'])}" + (f"<br/>Due: {_date(inv['due_date'])}" if inv.get("due_date") else ""), right),
    ]], colWidths=[110 * mm, 70 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black)]))

    buyer_lines = ["<font size=7 color='#555555'>BILL TO</font>", f"<b>{escape(buyer['name'])}</b>"]
    if buyer["city"]:
        buyer_lines.append(escape(buyer["city"]))
    contact = " · ".join(x for x in [buyer["phone"] and f"Ph: {buyer['phone']}", buyer["email"]] if x)
    if contact:
        buyer_lines.append(escape(contact))
    if buyer["gstin"]:
        buyer_lines.append(f"GSTIN: <b>{escape(buyer['gstin'])}</b>")
    ref = f"<br/>For: <b>{escape(data['reference'])}</b>" if data["reference"] else ""
    parties = Table([[
        Paragraph("<br/>".join(buyer_lines), body),
        Paragraph(f"<font size=7 color='#555555'>SOLD FROM</font><br/><b>{escape(seller['branch'] or '')}</b>{ref}", right),
    ]], colWidths=[110 * mm, 70 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    rows = [["#", "Item", "HSN", "Qty", "Rate", "Amount"]]
    for it in data["items"]:
        extra = " · ".join(x for x in [it["spec"], it["code"]] if x)
        item_cell = [p(it["description"])] + ([p(extra, small)] if extra else [])
        rows.append([str(it["n"]), item_cell, it["hsn"] or "-", str(it["qty"]), _money(it["rate"]), _money(it["amount"])])
    rows.append(["", "Total", "", str(data["total_qty"]), "", _money(data["total"])])
    lines = Table(rows, colWidths=[8 * mm, 80 * mm, 22 * mm, 14 * mm, 26 * mm, 30 * mm], repeatRows=1)
    lines.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#c9c9c9")),
        ("LINEBELOW", (0, -1), (-1, -1), 1.2, colors.black),
    ]))

    if inv["status"] == "Paid":
        payment = f"<b>PAID</b> on {_date(inv['paid_on'])} via {escape(inv['pay_method'] or '-')}"
        if inv.get("payment_reference"):
            payment += f" · Ref: {escape(inv['payment_reference'])}"
    elif inv["status"] in ("Cancelled", "Refunded"):
        payment = f"<b>{escape(inv['status'].upper())}</b>"
    else:
        payment = f"<b>Payment due:</b> {_money(data['total'])}"
    status_box = Table([[Paragraph(payment, body)]], colWidths=[180 * mm])
    status_box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9c9c9"))]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Invoice {inv['code']}", author=seller["name"], creator=seller["name"],
    )
    doc.build([
        head, Spacer(1, 4 * mm), parties, Spacer(1, 5 * mm), lines, Spacer(1, 3 * mm),
        Paragraph(f"Amount (INR): <b>{_money(data['total'])}</b>", body), Spacer(1, 4 * mm), status_box, Spacer(1, 14 * mm),
        Paragraph("Thank you for your business. This is a computer-generated invoice.", small),
        Paragraph(f"Generated {timezone.localtime().strftime('%d %b %Y %H:%M %Z')}", small),
    ])
    return buffer.getvalue()
