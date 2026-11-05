from datetime import date

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from reports.profit_loss import raw_figures

from .documents import invoice_document, render_invoice_pdf
from .models import Invoice, InvoiceItem

PERMS = ("invoices.view", "invoices.create", "invoices.settle", "invoices.refund")


class Base(APITestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="main", name="Main", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Asha", type=Party.RETAIL, phone="9876543210", joined=date(2026, 1, 1))
        self.product = Product.objects.create(brand="Dell", model_name="5420", product_code="VC-LAP-0001")
        self.variant = Variant.objects.create(product=self.product, code="V1", spec="16GB", mrp=60000, sell_price=50000, cost=30000)
        self.stock = Stock.objects.create(stock_point=self.shop, variant=self.variant, quantity=10)
        self.staff = make_user("sales", perms=PERMS, stock_point=self.shop)
        self.client = client_for(self.staff)

    def sell(self, qty=2, price=999, client=None, **extra):
        payload = {"party": self.party.pk, "stock_point": self.shop.pk, "date": timezone.localdate().isoformat(),
                   "items": [{"variant": self.variant.pk, "qty": qty, "price": price}], **extra}
        return (client or self.client).post("/api/invoices/", payload, format="json")

    def discounted(self, percent="10", **extra):
        response = self.sell(discount_percent=percent, discount_reason="Regular customer", **extra)
        self.assertEqual(response.status_code, 201, response.content)
        return Invoice.objects.get(pk=response.json()["id"]), response.json()

    def pay(self, invoice):
        self.assertEqual(self.client.post(f"/api/invoices/{invoice.pk}/settle/", {"pay_method": "Cash"}, format="json").status_code, 200)


class AmountTests(Base):
    def test_invoice_shows_subtotal_percentage_amount_and_total(self):
        _, data = self.discounted(price=1000)
        self.assertEqual((data["subtotal"], data["discount_amount"], data["total"]), (2000, 200, 1800))
        self.assertEqual(data["discount_percent"], "10.00")
        self.assertEqual(data["discount_by_name"], "sales")
        self.assertEqual(data["items"][-1]["product_name"], "Discount (10%)")
        self.assertTrue(data["items"][-1]["is_discount"])

    def test_rounds_to_the_nearest_rupee(self):
        _, data = self.discounted(percent="7.5", qty=1, price=999)
        self.assertEqual((data["discount_amount"], data["total"]), (75, 924))

    def test_print_and_pdf_show_the_discount(self):
        invoice, _ = self.discounted(price=1000)
        document = invoice_document(invoice)
        self.assertEqual(document["total"], 1800)
        self.assertIn("Discount (10%)", [item["description"] for item in document["items"]])
        self.assertTrue(render_invoice_pdf(invoice).startswith(b"%PDF"))

    def test_no_discount_changes_nothing(self):
        data = self.sell(price=1000).json()
        self.assertEqual((data["total"], data["discount_amount"]), (2000, 0))
        self.assertEqual(len(data["items"]), 1)

    def test_payment_books_and_profit_use_the_discounted_amount(self):
        invoice, _ = self.discounted(qty=1, price=50000)
        self.pay(invoice)
        today = timezone.localdate()
        figures = raw_figures([self.shop.pk], today, today)[self.shop.pk]
        self.assertEqual(figures["billed"][Invoice.SALE], 45000)
        self.assertEqual(figures["cost"][Invoice.SALE], 30000)
        self.assertEqual(figures["missing_cost_lines"], 0)
        self.assertEqual(figures["unlinked_sale_value"], 0)

    def test_stock_moves_only_for_products(self):
        invoice, _ = self.discounted(qty=2)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 8)
        self.client.post(f"/api/invoices/{invoice.pk}/cancel/", {"reason": "Mistake"}, format="json")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 10)


class RuleTests(Base):
    def test_reason_is_required(self):
        response = self.sell(discount_percent="5")
        self.assertEqual(response.status_code, 400)
        self.assertIn("discount_reason", response.json())

    def test_range(self):
        self.assertEqual(self.sell(discount_percent="-1", discount_reason="x").status_code, 400)
        self.assertEqual(self.sell(discount_percent="101", discount_reason="x").status_code, 400)

    def test_staff_limit_is_ten_percent(self):
        self.assertEqual(self.sell(discount_percent="10", discount_reason="x").status_code, 201)
        response = self.sell(discount_percent="10.01", discount_reason="x")
        self.assertEqual(response.status_code, 400)
        self.assertIn("need an Admin", str(response.json()))

    def test_admin_can_go_higher(self):
        admin = client_for(make_user("admin", perms=(*PERMS, "roles.manage"), stock_point=self.shop))
        response = self.sell(client=admin, discount_percent="40", discount_reason="Damaged box")
        self.assertEqual(response.status_code, 201, response.content)

    @override_settings(SALES_DISCOUNT_LIMIT=5)
    def test_limit_is_a_setting(self):
        self.assertEqual(self.sell(discount_percent="6", discount_reason="x").status_code, 400)

    def test_discount_cannot_be_written_as_a_line(self):
        response = self.sell(price=-500)
        self.assertEqual(response.status_code, 400)


class ChangeTests(Base):
    def revise(self, invoice, **body):
        return self.client.patch(f"/api/invoices/{invoice.pk}/", body, format="json")

    def test_revising_items_recalculates_the_discount(self):
        invoice, _ = self.discounted(qty=1, price=1000)
        response = self.revise(invoice, items=[{"variant": self.variant.pk, "qty": 3, "price": 1000}])
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["subtotal"], data["discount_amount"], data["total"]), (3000, 300, 2700))
        self.assertEqual(InvoiceItem.objects.filter(invoice=invoice, item_kind="discount").count(), 1)

    def test_discount_can_be_added_or_removed_while_unpaid(self):
        invoice = Invoice.objects.get(pk=self.sell(price=1000).json()["id"])
        added = self.revise(invoice, discount_percent="5", discount_reason="Festival offer").json()
        self.assertEqual(added["total"], 1900)
        removed = self.revise(invoice, discount_percent="0").json()
        self.assertEqual((removed["total"], removed["discount_reason"]), (2000, ""))

    def test_paid_invoice_discount_is_locked(self):
        invoice, _ = self.discounted()
        self.pay(invoice)
        self.assertEqual(self.revise(invoice, discount_percent="5", discount_reason="x").status_code, 400)

    def test_staff_cannot_raise_a_discount_past_the_limit_by_revising(self):
        invoice, _ = self.discounted()
        self.assertEqual(self.revise(invoice, discount_percent="50", discount_reason="x").status_code, 400)


class RefundTests(Base):
    def refund(self, invoice, line, qty):
        return self.client.post(f"/api/invoices/{invoice.pk}/refund/", {
            "method": "Cash", "reason": "Returned", "items": [{"item": line.pk, "qty": qty}]}, format="json")

    def test_a_return_refunds_what_the_customer_actually_paid(self):
        invoice, _ = self.discounted(qty=2, price=1000)
        self.pay(invoice)
        line = invoice.items.get(variant__isnull=False)
        response = self.refund(invoice, line, 1)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["refunded_total"], 900)

    def test_returning_everything_refunds_exactly_the_total(self):
        invoice, _ = self.discounted(percent="7.5", qty=3, price=999)
        self.pay(invoice)
        line = invoice.items.get(variant__isnull=False)
        for _ in range(3):
            self.assertEqual(self.refund(invoice, line, 1).status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.REFUNDED)
        self.assertEqual(invoice.refunded_total, invoice.total)

    def test_the_discount_line_cannot_be_returned(self):
        invoice, _ = self.discounted()
        self.pay(invoice)
        line = invoice.items.get(item_kind="discount")
        self.assertEqual(self.refund(invoice, line, 1).status_code, 400)
