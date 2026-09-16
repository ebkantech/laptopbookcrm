from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Permission, Role, User
from accounting.models import BankAccount, BankEntry, CashEntry
from broadcast.models import Campaign, WhatsAppOrder
from catalog.models import Part, PartStock, Product, Service, Stock, StockPoint, Variant
from parties.models import Message, Party
from rentals.models import Rental, RentalIssue
from repairs.models import Notification, RepairInvoice, RepairTicket
from sales.models import Invoice, InvoiceItem
from warranty.models import Warranty

PERMS = {
    "cashbook.view": "View the cash book",
    "cashbook.edit": "Add or edit cash entries",
    "bankbook.view": "View the bank book",
    "bankbook.edit": "Add or edit bank entries",
    "bankbook.reconcile": "Mark bank entries reconciled",
    "invoices.view": "View invoices",
    "invoices.create": "Create invoices & payment links",
    "invoices.settle": "Mark invoices settled",
    "inventory.edit": "Edit stock and product records",
    "rentals.manage": "Manage rental accounts",
    "rentals.view": "View rental assets",
    "rentals.approve": "Approve rental agreements on behalf of customers",
    "repairs.view": "View repair tickets",
    "repairs.manage": "Create tickets, update stages, and settle repair bills",
    "broadcast.send": "Send WhatsApp / email campaigns",
    "warranty.manage": "Register and edit customer warranties",
    "roles.manage": "Change roles and permissions",
    "reports.export": "Export accounting reports",
}

ROLES = {
    "owner": ("Owner", list(PERMS.keys())),
    "accountant": ("Accountant", [
        "cashbook.view", "cashbook.edit", "bankbook.view", "bankbook.edit",
        "bankbook.reconcile", "invoices.view", "invoices.settle", "repairs.view", "reports.export",
    ]),
    "manager": ("Store Manager", [
        "cashbook.view", "cashbook.edit", "bankbook.view", "invoices.view", "invoices.create",
        "invoices.settle", "inventory.edit", "rentals.view", "rentals.manage", "repairs.view", "repairs.manage",
        "broadcast.send", "warranty.manage",
    ]),
    "sales": ("Sales Executive", ["invoices.view", "invoices.create", "repairs.view", "repairs.manage", "broadcast.send", "warranty.manage"]),
    "auditor": ("Auditor \u2014 read only", ["cashbook.view", "bankbook.view", "invoices.view", "repairs.view", "reports.export"]),
}

USERS = [
    ("aman.kapoor", "Aman", "Kapoor", "owner"),
    ("ritu.sharma", "Ritu", "Sharma", "accountant"),
    ("vikram.sethi", "Vikram", "Sethi", "manager"),
    ("naina.joshi", "Naina", "Joshi", "sales"),
    ("deepa.iyer", "Deepa", "Iyer", "auditor"),
]

STOCK_POINTS = [
    ("kb", "Karol Bagh Store", "shop"),
    ("np", "Nehru Place Store", "shop"),
    ("ln", "Lajpat Nagar Store", "shop"),
    ("amazon", "Amazon", "online"),
    ("flipkart", "Flipkart", "online"),
    ("site", "Own Website", "online"),
    ("wa", "WhatsApp Orders", "online"),
]

BRANDS = ["Dell", "HP", "Lenovo", "Asus", "Acer", "Apple", "MSI"]

RAW_PRODUCTS = [
    ("Dell", "Latitude 5420", "Intel i5", "84713010", "Refurbished", 34999, [("8GB / 256GB SSD", 0), ("16GB / 512GB SSD", 6000)]),
    ("Dell", "XPS 13", "Intel i7", "84713010", "New", 89999, [("16GB / 512GB SSD", 0), ("32GB / 1TB SSD", 15000)]),
    ("HP", "EliteBook 840 G8", "Intel i7", "84713010", "Refurbished", 42999, [("16GB / 256GB SSD", 0), ("16GB / 512GB SSD", 4500)]),
    ("HP", "Pavilion 15", "AMD Ryzen 5", "84713010", "New", 47999, [("8GB / 512GB SSD", 0)]),
    ("Lenovo", "ThinkPad T14", "Intel i5", "84713010", "Refurbished", 36999, [("8GB / 256GB SSD", 0), ("16GB / 512GB SSD", 7000)]),
    ("Lenovo", "IdeaPad Slim 5", "AMD Ryzen 7", "84713010", "New", 54999, [("16GB / 512GB SSD", 0)]),
    ("Asus", "Vivobook 15", "Intel i3", "84713010", "New", 28999, [("8GB / 512GB SSD", 0)]),
    ("Asus", "ROG Strix G15", "AMD Ryzen 7", "84713010", "New", 79999, [("16GB / 1TB SSD", 0)]),
    ("Acer", "Aspire 7", "Intel i5", "84713010", "New", 41999, [("8GB / 512GB SSD", 0)]),
    ("Apple", "MacBook Air 13", "Apple M2", "84713010", "New", 99900, [("8GB / 256GB SSD", 0), ("16GB / 512GB SSD", 20000)]),
    ("MSI", "Modern 14", "Intel i7", "84713010", "Refurbished", 39999, [("16GB / 512GB SSD", 0)]),
    ("Dell", "Inspiron 15", "Intel i9", "84713010", "New", 74999, [("16GB / 1TB SSD", 0)]),
]

ACCESSORIES = [
    ("Universal 65W Type-C Charger", "Charger", 1299),
    ("Laptop Bag \u2014 15.6\" Water-resistant", "Bag", 899),
    ("Wireless Mouse", "Peripheral", 599),
    ("8GB DDR4 RAM Upgrade Kit", "Upgrade", 2199),
    ("Extended Warranty \u2014 1 Year", "Service", 2999),
]

PARTS = [
    ("screen", "15.6\" FHD Laptop Screen"),
    ("keyboard", "Replacement Keyboard Unit"),
    ("battery", "4-Cell Laptop Battery"),
    ("ram", "8GB DDR4 RAM Module"),
    ("chargerport", "DC Charging Port"),
    ("motherboard", "Motherboard (model-specific)"),
]

SERVICES = [
    ("screen", "Screen replacement", "Hardware", 3200, "screen"),
    ("keyboard", "Keyboard replacement", "Hardware", 1800, "keyboard"),
    ("battery", "Battery replacement", "Hardware", 2400, "battery"),
    ("ram", "RAM upgrade / replacement", "Hardware", 900, "ram"),
    ("chargerport", "Charging port repair", "Hardware", 1200, "chargerport"),
    ("motherboard", "Motherboard repair", "Hardware", 5200, "motherboard"),
    ("os", "OS installation / reinstall", "Software", 600, None),
    ("virus", "Virus / malware removal", "Software", 500, None),
    ("data-recovery", "Data recovery", "Software", 1500, None),
    ("software-tune", "Software troubleshooting", "Software", 400, None),
]

PARTIES = [
    ("Rahul Mehta", "Retail", "+91 98100 22341", "rahul.mehta@gmail.com", "", "Delhi", "2025-03-14"),
    ("Sneha Kapoor", "Retail", "+91 99110 33452", "sneha.kapoor@outlook.com", "", "Delhi", "2025-06-02"),
    ("Bright Minds School", "Dealer", "+91 98200 77812", "procurement@brightminds.edu.in", "07AABCB1122L1ZQ", "Delhi", "2024-11-20"),
    ("Arjun Verma", "Rental", "+91 97110 88231", "arjun.verma@proton.me", "", "Gurugram", "2026-01-10"),
    ("Nidhi Sharma", "Rental", "+91 98730 12938", "nidhi.sharma@gmail.com", "", "Delhi", "2026-02-22"),
    ("Kunal Studios Pvt Ltd", "Dealer", "+91 99580 44120", "accounts@kunalstudios.in", "07AAFCK9081M1Z3", "Noida", "2025-01-05"),
    ("Priya Nair", "Rental", "+91 98110 65432", "priya.nair@yahoo.com", "", "Delhi", "2026-04-18"),
    ("Deepak Chawla", "Retail", "+91 99680 21093", "deepak.c@gmail.com", "", "Faridabad", "2025-09-30"),
]


def seeded(i):
    import math
    x = math.sin(i * 999.77) * 10000
    return abs(x - int(x))


class Command(BaseCommand):
    help = "Seed the CRMBook demo dataset -- roles, catalogue, parties, invoices, rentals, repairs, accounting, broadcast."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding roles & permissions...")
        perms = {code: Permission.objects.update_or_create(codename=code, defaults={"description": desc})[0] for code, desc in PERMS.items()}
        roles = {}
        for slug, (label, perm_codes) in ROLES.items():
            role, _ = Role.objects.update_or_create(slug=slug, defaults={"label": label})
            role.permissions.set([perms[c] for c in perm_codes])
            roles[slug] = role

        self.stdout.write("Seeding staff users (password: crmbook123)...")
        for username, first, last, role_slug in USERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last, "role": roles[role_slug]}
            )
            if created:
                user.set_password("crmbook123")
                user.role = roles[role_slug]
                user.save()
        User.objects.filter(username="aman.kapoor").update(is_superuser=True, is_staff=True)

        self.stdout.write("Seeding stock points...")
        sps = {}
        for slug, name, kind in STOCK_POINTS:
            sps[slug], _ = StockPoint.objects.update_or_create(slug=slug, defaults={"name": name, "kind": kind})

        self.stdout.write("Seeding catalogue...")
        variant_lookup = {}
        pid = 0
        for i, (brand, model, proc, hsn, cond, base, variants) in enumerate(RAW_PRODUCTS):
            pid += 1
            product, _ = Product.objects.update_or_create(
                product_code=f"VC-LAP-{pid:04d}",
                defaults={"brand": brand, "model_name": model, "processor": proc, "hsn": hsn, "condition": cond},
            )
            for vi, (spec, delta) in enumerate(variants):
                sell = base + delta
                variant, _ = Variant.objects.update_or_create(
                    code=f"VC-SKU-{len(variant_lookup) + 1:04d}",
                    defaults={"product": product, "spec": spec, "mrp": sell + 3000, "sell_price": sell, "cost": round(sell * 0.78)},
                )
                variant_lookup[(brand, model, spec)] = variant
                for si, sp in enumerate(sps.values()):
                    qty = round(seeded(i * 31 + si * 7) * (9 if sp.kind == "shop" else 5))
                    Stock.objects.update_or_create(variant=variant, stock_point=sp, defaults={"quantity": qty})

        aid = 1000
        for i, (name, cat, price) in enumerate(ACCESSORIES):
            aid += 1
            product, _ = Product.objects.update_or_create(
                product_code=f"VC-ACC-{aid:04d}",
                defaults={"brand": "\u2014", "model_name": name, "processor": "", "hsn": "", "condition": "New"},
            )
            variant, _ = Variant.objects.update_or_create(
                code=f"VC-SKU-{len(variant_lookup) + 1:04d}",
                defaults={"product": product, "spec": cat, "mrp": price + 300, "sell_price": price, "cost": round(price * 0.62)},
            )
            for si, sp in enumerate(sps.values()):
                qty = round(seeded(i * 53 + si * 11 + 900) * 20)
                Stock.objects.update_or_create(variant=variant, stock_point=sp, defaults={"quantity": qty})

        self.stdout.write("Seeding parts & services...")
        non_apple = [b for b in BRANDS if b != "Apple"]
        parts = {}
        for slug, name in PARTS:
            parts[slug], _ = Part.objects.update_or_create(slug=slug, defaults={"name": name, "compatible_brands": non_apple})
            for si, sp in enumerate([s for s in sps.values() if s.kind == "shop"]):
                qty = round(seeded(hash(slug) % 97 * 41 + si * 13 + 500) * 7)
                PartStock.objects.update_or_create(part=parts[slug], stock_point=sp, defaults={"quantity": qty})

        services = {}
        for slug, label, seg, charge, part_slug in SERVICES:
            services[slug], _ = Service.objects.update_or_create(
                slug=slug, defaults={"label": label, "segment": seg, "charge": charge, "part": parts.get(part_slug)}
            )

        self.stdout.write("Seeding parties...")
        parties = {}
        for i, (name, ptype, phone, email, gstin, city, joined) in enumerate(PARTIES):
            p, _ = Party.objects.update_or_create(
                name=name, defaults={"type": ptype, "phone": phone, "email": email, "gstin": gstin, "city": city, "joined": joined}
            )
            parties[f"c{i + 1}"] = p

        self.stdout.write("Seeding a starter invoice, rental, ticket, and books...")
        v = list(variant_lookup.values())[0]
        if not Invoice.objects.exists():
            SAMPLE_INVOICES = [
                # code, party key, stock_point slug, date, status, pay_method, variant index (into variant_lookup), qty
                ("INV-3312", "c3", "kb", date(2026, 9, 5), Invoice.PAID, "Bank transfer", 0, 1),
                ("INV-3313", "c1", "site", date(2026, 9, 6), Invoice.LINK_SENT, "Razorpay link", 9, 1),
                ("INV-3314", "c8", "np", date(2026, 9, 4), Invoice.PAID, "UPI", 3, 1),
                ("INV-3315", "c6", "flipkart", date(2026, 9, 3), Invoice.OVERDUE, "Net banking", 6, 2),
                ("INV-3316", "c2", "wa", date(2026, 9, 6), Invoice.LINK_SENT, "Razorpay link", 5, 1),
                ("INV-3320", "c3", "amazon", date(2026, 9, 1), Invoice.PAID, "Bank transfer", 1, 1),
                ("INV-3321", "c4", "ln", date(2026, 8, 28), Invoice.PAID, "UPI", 4, 1),
                ("INV-3322", "c7", "kb", date(2026, 8, 30), Invoice.PAID, "Bank transfer", 2, 1),
            ]
            variants_by_index = list(variant_lookup.values())
            for code, pkey, sp_slug, d, status, pay_method, vidx, qty in SAMPLE_INVOICES:
                variant = variants_by_index[vidx % len(variants_by_index)]
                inv = Invoice.objects.create(
                    code=code, party=parties[pkey], stock_point=sps[sp_slug], date=d,
                    status=status, pay_method=pay_method,
                )
                InvoiceItem.objects.create(invoice=inv, variant=variant, qty=qty, price=variant.sell_price)

        if not Rental.objects.exists():
            SAMPLE_RENTALS = [
                ("c4", "Dell Latitude 5420", 2499, date(2026, 1, 10), 12, 8, 0, date(2026, 8, 10)),
                ("c5", "HP EliteBook 840 G8", 2199, date(2026, 2, 22), 6, 6, 2, date(2026, 8, 22)),
                ("c7", "Lenovo ThinkPad T14", 1999, date(2026, 4, 18), 12, 4, 3, date(2026, 7, 18)),
                ("c2", "Asus Vivobook 15", 1699, date(2026, 5, 2), 6, 3, 1, date(2026, 8, 2)),
                ("c8", "Acer Aspire 7", 1899, date(2026, 3, 11), 12, 5, 0, date(2026, 8, 11)),
                # extra units that share a model with one above, so the
                # dashboard's "recurring issue by model" panel has more
                # than a single lonely example
                ("c1", "Dell Latitude 5420", 2499, date(2026, 3, 2), 12, 5, 1, date(2026, 8, 2)),
                ("c6", "Asus Vivobook 15", 1699, date(2026, 2, 14), 12, 6, 0, date(2026, 8, 14)),
                ("c3", "Lenovo ThinkPad T14", 1999, date(2026, 5, 20), 6, 3, 0, date(2026, 8, 20)),
            ]
            rentals_by_key = {}
            for pkey, label, fee, start, tenure, paid, late, last_pay in SAMPLE_RENTALS:
                rentals_by_key[pkey] = Rental.objects.create(
                    party=parties[pkey], product_label=label, monthly_fee=fee, start=start,
                    tenure_months=tenure, months_paid=paid, late_count=late, tickets=0, last_payment=last_pay,
                )

            manager = User.objects.filter(username="vikram.sethi").first()

            # -- Recurring on the SAME unit (2+ issues, one rental each) --
            RentalIssue.objects.create(
                rental=rentals_by_key["c7"], title="Laptop overheating during use",
                description="Client reports the fan runs loud and the laptop shuts down after ~30 minutes of use.",
                status=RentalIssue.IN_PROGRESS, assigned_to=manager,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c7"], title="Overheating again after last repair",
                description="Same client, same overheating complaint, three weeks after the last fix.",
                status=RentalIssue.OPEN,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c1"], title="Battery draining fast",
                description="Client reports battery drops from 100% to 20% within two hours of light use.",
                status=RentalIssue.OPEN,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c1"], title="Wi-Fi disconnects randomly",
                description="Same client, separate complaint -- Wi-Fi drops every 10-15 minutes.",
                status=RentalIssue.IN_PROGRESS, assigned_to=User.objects.filter(username="naina.joshi").first(),
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c6"], title="Screen backlight flickering",
                description="Client says the screen flickers when the laptop is on battery power.",
                status=RentalIssue.OPEN,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c6"], title="Flickering worse after last check",
                description="Follow-up complaint -- same issue, more frequent now.",
                status=RentalIssue.IN_PROGRESS, assigned_to=manager,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c8"], title="Keyboard keys sticking",
                description="The space bar and left shift key stick intermittently.",
                status=RentalIssue.OPEN,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c8"], title="Sticking keys, now worse",
                description="Client says two more keys have started sticking since the first report.",
                status=RentalIssue.OPEN,
            )

            # -- Single issues that still feed the by-model grouping --
            RentalIssue.objects.create(
                rental=rentals_by_key["c3"], title="Fan making a loud grinding noise",
                description="Different client, same model as the c7 ThinkPad above -- worth checking if this batch has a fan defect.",
                status=RentalIssue.OPEN,
            )
            RentalIssue.objects.create(
                rental=rentals_by_key["c5"], title="Charger not included at handover",
                description="Client says no charger was provided with the unit.",
                status=RentalIssue.OPEN,
            )
            resolved = RentalIssue.objects.create(
                rental=rentals_by_key["c4"], title="Touchpad occasionally unresponsive",
                description="Intermittent touchpad issue, resolved after a driver update over a remote session.",
                status=RentalIssue.RESOLVED, assigned_to=manager,
            )
            RentalIssue.objects.filter(pk=resolved.pk).update(resolved_at=timezone.now())
            RentalIssue.objects.create(
                rental=rentals_by_key["c2"], title="Speakers crackling at high volume",
                description="Different client, same model as the c6 Vivobook above.",
                status=RentalIssue.OPEN,
            )

            # keep each rental's `tickets` count in sync with how many
            # issues it actually has, same as the live assign/resolve flow does
            for r in rentals_by_key.values():
                Rental.objects.filter(pk=r.pk).update(tickets=r.issues.count())

        if not RepairTicket.objects.exists():
            ticket = RepairTicket.objects.create(
                code="RPR-1041", party=parties["c1"], brand="Dell", model_name="Latitude 5420",
                serial="DL5420-8823X", stock_point=sps["kb"], issue="Screen has vertical lines.",
                status=RepairTicket.IN_PROGRESS, received=date(2026, 9, 4), expected=date(2026, 9, 9),
                payment=RepairTicket.ADVANCE, advance_paid=800,
            )
            ticket.services.add(services["screen"])
            Notification.objects.create(ticket=ticket, channel="whatsapp", text="Ticket RPR-1041 created.")

            # a second, already-delivered ticket -- this is the one
            # that's actually eligible for a Repair-section warranty,
            # since only completed/settled repairs qualify
            delivered = RepairTicket.objects.create(
                code="RPR-1040", party=parties["c8"], brand="Acer", model_name="Aspire 7",
                serial="ACAS7-5510K", stock_point=sps["np"], issue="Keyboard keys unresponsive.",
                status=RepairTicket.DELIVERED, received=date(2026, 8, 20), expected=date(2026, 8, 23),
                payment=RepairTicket.FULL, advance_paid=0,
            )
            delivered.services.add(services["keyboard"])
            RepairInvoice.objects.create(
                ticket=delivered, code="RPR-INV-1040", amount=1800,
                stock_point=sps["np"], status="Paid", date=date(2026, 8, 23),
            )
            Notification.objects.create(ticket=delivered, channel="whatsapp", text="Ticket RPR-1040 created.")
            Notification.objects.create(ticket=delivered, channel="whatsapp", text="Keyboard replaced, ready for pickup.")

        owner = User.objects.get(username="aman.kapoor")
        if not CashEntry.objects.exists():
            CashEntry.objects.create(date=date(2026, 9, 1), particulars="Opening balance", type="in", amount=42000, by=owner)
            CashEntry.objects.create(date=date(2026, 9, 2), particulars="Cash sale, Karol Bagh", type="in", amount=18500, by=owner)

        if not BankAccount.objects.exists():
            hdfc = BankAccount.objects.create(name="HDFC Bank \u2014 Current A/c \u2022\u20224821", opening=612000)
            BankEntry.objects.create(account=hdfc, date=date(2026, 9, 1), particulars="Opening balance", type="in", amount=612000, reconciled=True)
            BankEntry.objects.create(account=hdfc, date=date(2026, 9, 3), particulars="NEFT \u2014 Bright Minds School", type="in", amount=209994, reconciled=True)

        if not Campaign.objects.exists():
            Campaign.objects.create(title="Diwali laptop offer \u2014 flat 12% off refurbished", channel="whatsapp", audience="All retail customers", sent=412, opened=301)

        if not WhatsAppOrder.objects.exists():
            WhatsAppOrder.objects.create(party=parties["c2"], text="Hi, do you have the Lenovo IdeaPad Slim 5 in stock?", status="New")

        if not Warranty.objects.exists():
            sales_invoice = Invoice.objects.filter(code="INV-3312").first()  # c3, Paid
            if sales_invoice:
                Warranty.objects.create(
                    party=sales_invoice.party, section=Warranty.SALES,
                    item_label="Dell Latitude 5420 \u2014 bulk order (6 units)",
                    invoice=sales_invoice, start_date=sales_invoice.date,
                    end_date=sales_invoice.date + timedelta(days=365),
                    notes="Standard 1-year manufacturer warranty on new purchase.",
                )

            repair_ticket = RepairTicket.objects.filter(code="RPR-1040").first()  # c8, Delivered
            if repair_ticket and repair_ticket.original_invoice:
                Warranty.objects.create(
                    party=repair_ticket.party, section=Warranty.REPAIR,
                    item_label=f"Keyboard replacement \u2014 {repair_ticket.brand} {repair_ticket.model_name}",
                    repair_ticket=repair_ticket, start_date=repair_ticket.original_invoice.date,
                    end_date=repair_ticket.original_invoice.date + timedelta(days=90),
                    notes="90-day service warranty on the replaced part and labour.",
                )

            rental = Rental.objects.filter(party=parties["c4"]).first()
            if rental:
                Warranty.objects.create(
                    party=rental.party, section=Warranty.RENTAL,
                    item_label=f"Rental equipment protection \u2014 {rental.product_label}",
                    start_date=rental.start, end_date=rental.start + timedelta(days=30 * rental.tenure_months),
                    notes="Covers hardware failure not caused by misuse for the full rental tenure.",
                )

        self.stdout.write(self.style.SUCCESS("Seed complete. Log in as aman.kapoor / crmbook123 (superuser) or any user in accounts.User with password crmbook123."))
