"""Sales, repair and rental invoices all live in one ledger with one INV
sequence; payment happens only in Sales & Invoices and flows back."""
import os
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase

from catalog.models import Product, Service, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Message, Party
from rentals.models import Rental, RentalAsset, RentalLine, add_months
from repairs.models import RepairTicket
from repairs.services import approve_on_behalf, finalize_estimate
from sales.models import Invoice


@mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"})
class UnifiedLedgerTests(TestCase):
    def setUp(self):
        self.owner = make_user("ledger-owner", superuser=True)
        self.client_ = client_for(self.owner)
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Ledger Customer", type=Party.RENTAL, phone="9876543210", joined=date.today())
        product = Product.objects.create(model_name="Laptop", product_code="TEST-LAP-0001")
        self.variant = Variant.objects.create(product=product, code="TEST-SKU-0001", spec="Base", mrp=1, sell_price=40000, cost=1)
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=5)
        self.service = Service.objects.create(slug="screen", label="Screen replacement", segment=Service.HARDWARE, charge=6000)

    # -- helpers --------------------------------------------------------
    def sell(self):
        return self.client_.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "items": [{"variant": self.variant.id, "qty": 1, "price": 40000}],
        }, format="json").json()

    def approved_ticket(self, advance=0, code="RPR-2001"):
        ticket = RepairTicket.objects.create(
            code=code, party=self.party, brand="Dell", model_name="Inspiron", stock_point=self.shop,
            issue="Cracked screen", status=RepairTicket.DIAGNOSING, received=date.today(), advance_paid=advance,
        )
        finalize_estimate(ticket, self.owner, [
            {"service": self.service, "description": "Screen replacement", "quantity": 1, "unit_price": 6000},
            {"service": None, "description": "Labour", "quantity": 1, "unit_price": 500},
        ])
        approve_on_behalf(ticket, self.owner, "Customer approved at the counter")
        RepairTicket.objects.filter(pk=ticket.pk).update(status=RepairTicket.READY)
        ticket.refresh_from_db()
        return ticket

    def rental(self, start=None, tenure=3):
        rental = Rental.objects.create(
            party=self.party, agreement_code="RNT-000777", product_label="2 rental devices", monthly_fee=4500,
            start=start or date.today(), tenure_months=tenure, last_payment=start or date.today(), status=Rental.ACTIVE,
        )
        for i, fee in enumerate([2000, 2500], start=1):
            asset = RentalAsset.objects.create(asset_tag=f"AST-{i}", serial_number=f"SN-{i}", brand="Dell", model_name=f"Model {i}")
            RentalLine.objects.create(rental=rental, asset=asset, monthly_fee=fee)
        return rental

    def pay(self, invoice_id, **extra):
        return self.client_.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash", **extra}, format="json")

    # -- one sequence ---------------------------------------------------
    def test_sale_repair_and_rent_share_one_invoice_sequence(self):
        sale = self.sell()
        ticket = self.approved_ticket()
        self.client_.post(f"/api/tickets/{ticket.id}/settle/")
        rental = self.rental()
        rent = self.client_.post(f"/api/rentals/{rental.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json").json()

        repair_code = Invoice.objects.get(source=Invoice.REPAIR).code
        n = int(sale["code"].split("-")[1])
        self.assertEqual([sale["code"], repair_code, rent["invoice_code"]], [f"INV-{n}", f"INV-{n + 1}", f"INV-{n + 2}"])

        listed = results(self.client_.get("/api/invoices/"))
        self.assertEqual(sorted(i["source"] for i in listed), ["rental", "repair", "sale"])
        self.assertEqual([i["code"] for i in results(self.client_.get("/api/invoices/", {"source": "repair"}))], [repair_code])

    # -- repairs --------------------------------------------------------
    def test_repair_delivery_raises_unpaid_invoice_paid_only_in_invoices(self):
        ticket = self.approved_ticket(advance=1500)
        response = self.client_.post(f"/api/tickets/{ticket.id}/settle/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], RepairTicket.DELIVERED)

        invoice = Invoice.objects.get(repair_ticket=ticket)
        self.assertEqual((invoice.source, invoice.status), (Invoice.REPAIR, Invoice.LINK_SENT))
        self.assertEqual(
            [(i.description, i.price) for i in invoice.items.all()],
            [("Screen replacement", 6000), ("Labour", 500), ("Less: advance received", -1500)],
        )
        self.assertEqual(invoice.total, 5000)
        self.assertEqual(response.json()["invoice"]["code"], invoice.code)
        # can't be invoiced twice
        self.assertEqual(self.client_.post(f"/api/tickets/{ticket.id}/settle/").status_code, 400)

        self.assertEqual(self.pay(invoice.id).status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.PAID)

    def test_fully_covered_repair_is_closed_without_payment(self):
        ticket = self.approved_ticket(advance=6500)
        self.client_.post(f"/api/tickets/{ticket.id}/settle/")
        invoice = Invoice.objects.get(repair_ticket=ticket)
        self.assertEqual((invoice.status, invoice.pay_method, invoice.total), (Invoice.PAID, "No charge", 0))

    def test_repair_print_data_uses_line_descriptions(self):
        ticket = self.approved_ticket()
        self.client_.post(f"/api/tickets/{ticket.id}/settle/")
        invoice = Invoice.objects.get(repair_ticket=ticket)
        data = self.client_.get(f"/api/invoices/{invoice.id}/print-data/").json()
        self.assertEqual([i["description"] for i in data["items"]], ["Screen replacement", "Labour"])
        self.assertEqual(data["reference"], f"Repair {ticket.code}")

    # -- rentals --------------------------------------------------------
    def test_rent_invoice_bills_next_month_and_is_sent_to_customer(self):
        start = date(2026, 1, 15)
        rental = self.rental(start=start)
        url = f"/api/rentals/{rental.id}/raise-invoice/"
        self.assertEqual(self.client_.post(url, {}, format="json").status_code, 400)  # needs issuing shop

        first = self.client_.post(url, {"stock_point": self.shop.id}, format="json")
        self.assertEqual(first.status_code, 201, first.content)
        inv1 = Invoice.objects.get(code=first.json()["invoice_code"])
        self.assertEqual((inv1.source, inv1.rental, inv1.date), (Invoice.RENTAL, rental, date.today()))
        self.assertEqual((inv1.period_start, inv1.period_end), (start, date(2026, 2, 14)))
        self.assertEqual(inv1.total, 4500)
        self.assertEqual([i.description for i in inv1.items.all()], ["Rent: Dell Model 1 (S/N SN-1)", "Rent: Dell Model 2 (S/N SN-2)"])
        msg = Message.objects.get(party=self.party)
        self.assertIn(inv1.code, msg.body)

        # each send is its own invoice number for the following month
        inv2 = Invoice.objects.get(code=self.client_.post(url, {"stock_point": self.shop.id}, format="json").json()["invoice_code"])
        self.assertNotEqual(inv1.code, inv2.code)
        self.assertEqual(inv2.period_start, add_months(start, 1))
        self.client_.post(url, {"stock_point": self.shop.id}, format="json")
        # 3-month tenure fully billed
        self.assertEqual(self.client_.post(url, {"stock_point": self.shop.id}, format="json").status_code, 400)

        data = self.client_.get(f"/api/rentals/{rental.id}/").json()
        self.assertEqual(len(data["rent_invoices"]), 3)
        self.assertIsNone(data["next_billing_period"])

    def test_paying_rent_updates_the_agreement(self):
        start = date.today() - timedelta(days=10)
        rental = self.rental(start=start)
        code = self.client_.post(f"/api/rentals/{rental.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json").json()["invoice_code"]
        invoice = Invoice.objects.get(code=code)

        self.assertEqual(self.pay(invoice.id, paid_on=date.today().isoformat()).status_code, 200)
        rental.refresh_from_db()
        self.assertEqual((rental.months_paid, rental.last_payment), (1, start))
        self.assertEqual(rental.late_count, 1)  # paid after the month's due date
        self.assertEqual(rental.next_payment_date, add_months(start, 1))

    def test_rental_payment_counters_cannot_be_edited_by_hand(self):
        rental = self.rental()
        self.client_.patch(f"/api/rentals/{rental.id}/", {"months_paid": 3, "late_count": 0}, format="json")
        rental.refresh_from_db()
        self.assertEqual(rental.months_paid, 0)

    def test_draft_rental_cannot_be_billed(self):
        rental = self.rental()
        Rental.objects.filter(pk=rental.pk).update(status=Rental.DRAFT)
        response = self.client_.post(f"/api/rentals/{rental.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_rental_staff_need_rentals_manage_to_raise(self):
        viewer = client_for(make_user("rental-viewer", ["rentals.view"]))
        rental = self.rental()
        self.assertEqual(viewer.post(f"/api/rentals/{rental.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json").status_code, 403)

    # -- dashboard ------------------------------------------------------
    def test_dashboard_splits_revenue_by_source_and_collects_everything(self):
        sale = self.sell()
        self.pay(sale["id"])
        ticket = self.approved_ticket()
        self.client_.post(f"/api/tickets/{ticket.id}/settle/")  # 6500 unpaid
        data = self.client_.get("/api/dashboard/summary/").json()
        self.assertEqual(data["revenue_paid"], 40000)
        self.assertEqual(data["pending_collections"], 6500)
        self.assertEqual(data["repair_revenue_paid"], 0)
        self.pay(Invoice.objects.get(source=Invoice.REPAIR).id)
        self.assertEqual(self.client_.get("/api/dashboard/summary/").json()["repair_revenue_paid"], 6500)

    def test_legacy_rental_without_device_lines_bills_its_monthly_fee(self):
        rental = Rental.objects.create(
            party=self.party, product_label="Asus Vivobook 15", monthly_fee=1699, start=date(2026, 3, 2),
            tenure_months=6, months_paid=3, last_payment=date(2026, 6, 2), status=Rental.ACTIVE,
        )
        data = self.client_.get(f"/api/rentals/{rental.id}/").json()
        self.assertEqual(data["total_monthly_fee"], 1699)
        code = self.client_.post(f"/api/rentals/{rental.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json").json()["invoice_code"]
        invoice = Invoice.objects.get(code=code)
        self.assertEqual((invoice.total, invoice.period_start), (1699, date(2026, 6, 2)))
