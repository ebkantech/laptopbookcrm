"""The rental agreement as a PDF, to print, sign and upload back."""
from io import BytesIO

from django.conf import settings
from django.utils import timezone


def _money(value):
    return f"Rs {value:,}"


def render_agreement_pdf(rental):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from . import onboarding
    from .billing import default_stock_point
    from .models import add_months

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))
    heading = ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold", fontSize=10.5, spaceBefore=8, spaceAfter=3)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=15, leading=19)
    text = lambda value, style=body: Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)

    party = rental.party
    shop = default_stock_point(rental)
    code = rental.agreement_code or f"RENTAL-{rental.pk}"
    fee = rental.total_monthly_fee
    last_day = add_months(rental.start, rental.tenure_months)
    lines = list(rental.lines.select_related("asset"))

    head = Table([[
        [text(settings.BUSINESS_NAME, title), text(shop.name if shop else "", small)],
        [text("RENTAL AGREEMENT", heading), text(f"No. {code}"), text(f"Date: {timezone.localdate():%d %b %Y}")],
    ]], colWidths=[110 * mm, 70 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black)]))

    customer = [f"<b>{escape(party.name)}</b>"]
    for value in (party.city, party.phone and f"Ph: {party.phone}", party.email, party.gstin and f"GSTIN: {party.gstin}"):
        if value:
            customer.append(escape(value))

    devices = [["#", "Device", "Serial number", "Rent / month"]]
    for number, line in enumerate(lines, start=1):
        devices.append([str(number), text(line.description), text(line.asset.serial_number), _money(line.monthly_fee)])
    if not lines:
        devices.append(["1", text(rental.product_label), "-", _money(fee)])
    devices.append(["", "Total monthly rent", "", _money(fee)])
    device_table = Table(devices, colWidths=[8 * mm, 92 * mm, 50 * mm, 30 * mm], repeatRows=1)
    device_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#c9c9c9")), ("LINEBELOW", (0, -1), (-1, -1), 1.2, colors.black),
    ]))

    rows = [["Start date", f"{rental.start:%d %b %Y}"], ["Tenure", f"{rental.tenure_months} month(s), ending before {last_day:%d %b %Y}"],
            ["Monthly rent", _money(fee)], ["Billing cycle", rental.get_payment_interval_months_display()]]
    state = onboarding.status(rental)
    if state.get("required"):
        if state["deposit_required"]:
            rows.append(["Security deposit (refundable)", _money(state["deposit"]["total"] if state["deposit"] else fee)])
        rows.append(["Advance rent (first month)", _money(state["advance"]["total"] if state["advance"] else fee)])
    summary = Table(rows, colWidths=[70 * mm, 110 * mm])
    summary.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9.5), ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9.5),
                                 ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd"))]))

    signatures = Table([["Customer signature", "", f"For {settings.BUSINESS_NAME}"], ["", "", ""],
                        ["Name: " + party.name, "", "Name:"], ["Date:", "", "Date:"]],
                       colWidths=[80 * mm, 20 * mm, 80 * mm], rowHeights=[6 * mm, 18 * mm, 6 * mm, 6 * mm])
    signatures.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                                    ("LINEBELOW", (0, 1), (0, 1), 0.8, colors.black), ("LINEBELOW", (2, 1), (2, 1), 0.8, colors.black)]))

    story = [head, Spacer(1, 4 * mm), text("Customer", heading), Paragraph("<br/>".join(customer), body),
             text("Devices", heading), device_table, text("Rental terms", heading), summary]
    if rental.terms:
        story += [text("Conditions", heading), text(rental.terms)]
    story += [Spacer(1, 12 * mm), signatures]
    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                      title=f"Rental agreement {code}", author=settings.BUSINESS_NAME).build(story)
    return buffer.getvalue()
