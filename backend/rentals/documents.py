"""
The rental agreement as a PDF, to print, sign and upload back.

Laid out like the business's own paper contract ("Rental Contract for
Computer System or Laptop System"):

  page 1  letterhead, rental period, CUSTOMER DETAILS, the Terms and
          Conditions (with the business's name in them, plus any extra
          conditions typed on the agreement), signatures
  page 2  SYSTEM DETAIL for every device (from the device and its product's
          specifications), Software and Network (blank lines to fill in on
          handover), Payment Detail (monthly rent in advance, security
          deposit and when it's returned), signatures

The business name, phone, email and address come from Settings -> Business
& messages (blank fields fall back to .env BUSINESS_*); the issuing shop's
own address / phone (Store Locator) win when set. Conditions edited there
replace the standard ones.
"""
from datetime import timedelta
from io import BytesIO

from django.utils import timezone

DOTS = "…" * 30


def _money(value):
    return f"Rs {value:,}/-"


def terms(name):
    """The standard conditions, worded as on the business's paper contract."""
    return [
        f"The rental period is as specified by {name} above.",
        "A service visit will be made within 24 to 48 hours of the customer's call.",
        "If rental equipment cannot be returned in rentable condition because of damage or theft, the rental period will "
        "finish on the date the equipment is replaced by the customer or an invoice for replacement is paid.",
        f"The equipment shall remain the property of {name} and the Customer shall not sell, exchange, pledge or part "
        "possession with the equipment.",
        "The Customer shall not service or repair the equipment, nor deface or remove any identification from the equipment.",
        f"The Customer shall notify {name} immediately of any loss of or damage to the equipment.",
        "The Customer is responsible for the safe custody of the equipment and accessories and shall be liable for any loss, "
        "theft or damage to the equipment however it has been caused.",
        f"The amount to repair or replace the damage or loss, plus lost rental revenue, is at the sole discretion of {name}.",
        f"{name} warrants that the equipment functions in accordance with the manufacturer's specifications. {name} is not "
        "responsible or liable for the failure of the equipment to perform the task for which it was rented by the Customer. "
        f"{name} shall, at its own expense, repair or replace faulty equipment at the earliest possible time. Work carried "
        "out for causes other than hardware failure will be charged to the customer.",
        f"{name} will, whenever possible, protect the customer's data security and right to confidentiality by scanning for "
        "viruses and reformatting hard disks before they are rented. The customer agrees not to hold "
        f"{name} responsible for any loss or losses arising from omission of this service.",
    ]


def _device_rows(line):
    """SYSTEM DETAIL for one rented device: what's known about it, blanks for the rest."""
    from catalog.models import StockSerial

    asset = line.asset
    variant = asset.variant
    product = variant.product if variant else None
    specs = (product.specs or {}) if product else {}
    unit = StockSerial.objects.filter(serial_number__iexact=asset.serial_number).select_related("purchase").first()
    bought = unit.purchase.purchased_on if unit and unit.purchase_id else None
    worth = asset.purchase_price or (variant.cost if variant else 0)
    accessories = ", ".join(a.get("name", "") for a in (line.accessories or []) if a.get("name"))
    processor = " ".join(x for x in [specs.get("processor") or (product.processor if product else ""), specs.get("generation")] if x)
    return [
        ("System code number / System name", f"{asset.asset_tag} — {asset.brand} {asset.model_name}".strip()),
        ("Serial number", asset.serial_number),
        ("Date / year of purchase", f"{bought:%d %b %Y}" if bought else f"In rental fleet since {asset.created_at:%d %b %Y}"),
        ("Branded", f"Yes ({asset.brand})" if asset.brand else "No (Assembled)"),
        ("Processor", processor or DOTS),
        ("RAM", specs.get("ram") or DOTS),
        ("Hard disk / Storage", specs.get("storage") or DOTS),
        ("Screen / Monitor", specs.get("screen_size") or DOTS),
        ("Others / accessories", accessories or DOTS),
        ("Condition at handover", line.condition_notes or DOTS),
        ("Rent", f"{_money(line.monthly_fee)} per month"),
        ("Worth (in Rupees)", f"{_money(worth)} / unit" if worth else DOTS),
    ]


def render_agreement_pdf(rental):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from . import onboarding
    from .billing import default_stock_point
    from .models import add_months

    from branding import texts

    biz = texts.business()  # Settings -> Business & messages (blank -> .env BUSINESS_*)
    name = biz.name
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
    center = ParagraphStyle("center", parent=body, alignment=1)
    brand = ParagraphStyle("brand", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=21, alignment=1)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=16, alignment=1, spaceBefore=4)
    section = ParagraphStyle("section", parent=body, fontName="Helvetica-Bold", fontSize=10.5, alignment=1, spaceBefore=8, spaceAfter=4)
    clause = ParagraphStyle("clause", parent=body, fontSize=9, leading=12, leftIndent=14, firstLineIndent=-14, spaceAfter=2.5)
    text = lambda value, style=body: Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)

    party = rental.party
    shop = default_stock_point(rental)
    code = rental.agreement_code or f"RENTAL-{rental.pk}"
    lines = list(rental.lines.select_related("asset__variant__product").order_by("id"))
    fee = rental.total_monthly_fee
    end = add_months(rental.start, rental.tenure_months) - timedelta(days=1)
    state = onboarding.status(rental)

    # -- letterhead -----------------------------------------------------------
    address = (shop.address if shop and shop.address else biz.address).strip()
    phone = (shop.phone if shop and shop.phone else "") or biz.phone
    letterhead = [text(name.upper(), brand)]
    if address:
        letterhead.append(text(address, center))
    contact = " · ".join(x for x in [phone and f"Contact: {phone}", biz.email and f"Email: {biz.email}"] if x)
    if contact:
        letterhead.append(text(contact, center))
    head = Table([[letterhead]], colWidths=[180 * mm])
    head.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.black), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))

    def details(rows, label_width=70):
        table = Table([[text(k), ":", text(v)] for k, v in rows], colWidths=[label_width * mm, 5 * mm, (175 - label_width) * mm])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        return table

    def signatures():
        sig = Table([["", "", ""], ["Customer's Signature", "", "Provider's Signature"],
                     [party.name, "", f"For {name}"]], colWidths=[70 * mm, 40 * mm, 70 * mm], rowHeights=[16 * mm, 6 * mm, 5 * mm])
        sig.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 9.5),
                                 ("LINEBELOW", (0, 0), (0, 0), 0.8, colors.black), ("LINEBELOW", (2, 0), (2, 0), 0.8, colors.black),
                                 ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#555555"))]))
        return KeepTogether([Spacer(1, 8 * mm), sig])

    # -- page 1 ---------------------------------------------------------------
    if lines:
        rental_for = "\n".join(
            f"{n}. {line.asset.brand} {line.asset.model_name}".strip()
            + (f" ({line.asset.variant.spec})" if line.asset.variant_id and line.asset.variant.spec else "")
            + f" — S/N {line.asset.serial_number}"
            for n, line in enumerate(lines, start=1))
        fees = {line.monthly_fee for line in lines}
        rate = (f"{_money(fees.pop())} per month / per piece" if len(fees) == 1 else "As per System Detail")
        if len(lines) > 1:
            rate += f" — {_money(fee)} per month for {len(lines)} pieces"
    else:
        rental_for, rate = rental.product_label, f"{_money(fee)} per month"

    customer_rows = [
        ("Name of the Party / Company", party.name),
        ("Address and Location", party.city or DOTS),
        ("Contact Person", party.name),
        ("Contact Person Mobile Number", party.phone),
        ("Email Address", party.email or DOTS),
    ]
    if party.gstin:
        customer_rows.append(("GSTIN", party.gstin))
    customer_rows += [("Rental for", rental_for), ("Rate (in Rupees)", rate),
                      ("Billing", f"{rental.get_payment_interval_months_display()}, rent payable in advance")]

    # conditions edited in Settings replace the standard ones; {business} becomes the name
    standard = terms(name)
    edited = [c.replace("{business}", name) for c in biz.rental_terms]
    clauses = (edited or standard) + [c.strip() for c in (rental.terms or "").splitlines() if c.strip()]
    story = [
        head, Spacer(1, 3 * mm),
        text("Rental Contract for Computer System or Laptop System", title),
        text(f"Agreement No. {code} · Dated {timezone.localdate():%d %b %Y}", center),
        text(f"Rental Period from {rental.start:%d %B %Y} to {end:%d %B %Y} ({rental.tenure_months} month{'s' if rental.tenure_months != 1 else ''})", center),
        text("CUSTOMER DETAILS", section), details(customer_rows),
        text("Terms and Conditions", section),
        *[Paragraph(f"{n}.&nbsp;&nbsp;{escape(c)}", clause) for n, c in enumerate(clauses, start=1)],
        signatures(),
        PageBreak(),
    ]

    # -- page 2 ---------------------------------------------------------------
    story += [head, Spacer(1, 2 * mm), text("SYSTEM DETAIL", section)]
    if lines:
        for n, line in enumerate(lines, start=1):
            block = [text(f"Device {n} of {len(lines)}", ParagraphStyle("dev", parent=body, fontName="Helvetica-Bold"))] if len(lines) > 1 else []
            rows = _device_rows(line)
            block.append(details([(f"{i}. {k}", v) for i, (k, v) in enumerate(rows, start=1)]))
            story.append(KeepTogether(block + [Spacer(1, 3 * mm)]))
        story.append(details([("Quantity of systems", f"{len(lines)} No{'s' if len(lines) > 1 else ''}")]))
    else:
        story.append(details([("1. System", rental.product_label), ("2. Quantity of systems", "1 No")]))

    story += [
        text("Software Detail", section),
        details([("1. System software", DOTS), ("2. Application software", DOTS)]),
        text("Network", section),
        details([("1. IP Address", DOTS), ("2. Subnet Mask", DOTS), ("3. Default Gateway", DOTS),
                 ("4. Preferred DNS Server", DOTS), ("5. Alternate DNS Server", DOTS), ("6. ISP", DOTS),
                 ("     a) User ID", DOTS), ("     b) Password", DOTS), ("7. WINS Server", DOTS)]),
    ]

    def received(row):
        if not row:
            return ""
        return " received" if row["status"] == "Paid" else " to be paid"

    pay_rows = []
    if state.get("required"):
        advance = state.get("advance")
        pay_rows.append(("Total amount due for every month (advance)", f"{_money(advance['total'] if advance else fee)}{received(advance)}"))
        if state.get("deposit_required"):
            deposit = state.get("deposit")
            pay_rows.append((f"Security deposit (will be returned on {add_months(rental.start, rental.tenure_months):%d %B %Y})",
                             f"{_money(deposit['total'] if deposit else fee)}{received(deposit)}"))
    else:
        pay_rows.append(("Total amount due for every month (advance)", _money(fee)))
    story += [text("Payment Detail", section), details(pay_rows, label_width=95), signatures()]

    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=13 * mm, bottomMargin=13 * mm,
                      title=f"Rental agreement {code}", author=name).build(story)
    return buffer.getvalue()
