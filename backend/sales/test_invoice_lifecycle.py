"""Stock checks on sale, due dates / overdue, and cancelling invoices."""
import os
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Party
from rentals.models import Rental
from sales.models import Invoice, InvoiceItem, PaymentLink
from sales.services import mark_overdue


@mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "sandbox", "UPI_LOOKUP_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"})
class InvoiceLifecycleTests(TestCase):
    def setUp(self):
        self.staff = client_for(make_user("seller", ["invoices.view", "invoices.create", "invoices.settle", "payments.send_link", "rentals.view", "rentals.manage"]))
        self.shop = StockPoint.objects.create(slug="shop", name="Main Shop", kind=StockPoint.SHOP)
        self.other_shop = StockPoint.objects.create(slug="other", name="Other Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Buyer", type=Party.RENTAL, phone="9876543211", joined=date.today())
        product = Product.objects.create(model_name="Laptop", product_code="P-1")
        self.a = Variant.objects.create(product=product, code="V-A", spec="8GB", mrp=1, sell_price=40000, cost=1)
        self.b = Variant.objects.create(product=product, code="V-B", spec="16GB", mrp=1, sell_price=50000, cost=1)
        self.stock_a = Stock.objects.create(variant=self.a, stock_point=self.shop, quantity=2)
        self.stock_b = Stock.objects.create(variant=self.b, stock_point=self.shop, quantity=5)

    def sell(self, items, stock_point=None):
        return self.staff.post("/api/invoices/", {
            "party": self.party.id, "stock_point": (stock_point or self.shop).id, "date": date.today().isoformat(), "items": items,
        }, format="json")

    # -- selling -------------------------------------------------------
    def test_multi_line_sale_with_negotiated_price(self):
        response = self.sell([{"variant": self.a.id, "qty": 2, "price": 38000}, {"variant": self.b.id, "qty": 1, "price": 50000}])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["total"], 2 * 38000 + 50000)
        self.assertEqual(response.json()["due_date"], (date.today() + timedelta(days=7)).isoformat())
        self.stock_a.refresh_from_db()
        self.stock_b.refresh_from_db()
        self.assertEqual((self.stock_a.quantity, self.stock_b.quantity), (0, 4))

    def test_cannot_sell_more_than_is_on_the_shelf(self):
        response = self.sell([{"variant": self.a.id, "qty": 3, "price": 1}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("only 2 in stock at Main Shop", response.json()["items"][0])
        # the same variant on two lines counts together
        self.assertEqual(self.sell([{"variant": self.a.id, "qty": 2, "price": 1}, {"variant": self.a.id, "qty": 1, "price": 1}]).status_code, 400)
        self.assertIn("isn't stocked at Other Shop", self.sell([{"variant": self.a.id, "qty": 1, "price": 1}], self.other_shop).json()["items"][0])
        self.assertEqual(self.sell([{"variant": self.a.id, "qty": 0, "price": 1}]).status_code, 400)
        self.assertFalse(Invoice.objects.exists())
        self.stock_a.refresh_from_db()
        self.assertEqual(self.stock_a.quantity, 2)

    # -- overdue -------------------------------------------------------
    def test_unpaid_invoices_go_overdue_after_the_due_date(self):
        inv = Invoice.objects.get(pk=self.sell([{"variant": self.b.id, "qty": 1, "price": 1}]).json()["id"])
        self.assertEqual(mark_overdue(), 0)
        Invoice.objects.filter(pk=inv.pk).update(due_date=date.today() - timedelta(days=1))
        listed = results(self.staff.get("/api/invoices/"))
        self.assertEqual(listed[0]["status"], Invoice.OVERDUE)

    # -- cancelling ----------------------------------------------------
    def test_cancel_unpaid_sale_puts_stock_back_and_kills_the_payment_link(self):
        body = self.sell([{"variant": self.a.id, "qty": 2, "price": 1}]).json()
        self.staff.post(f"/api/invoices/{body['id']}/send-upi-link/", {}, format="json")
        self.assertEqual(self.staff.post(f"/api/invoices/{body['id']}/cancel/", {}, format="json").status_code, 400)  # reason needed
        response = self.staff.post(f"/api/invoices/{body['id']}/cancel/", {"reason": "Customer changed their mind"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["status"], response.json()["cancelled_by_name"]), ("Cancelled", "seller"))
        self.stock_a.refresh_from_db()
        self.assertEqual(self.stock_a.quantity, 2)
        self.assertEqual(PaymentLink.objects.get().status, PaymentLink.CANCELLED)
        # can't be paid or re-cancelled afterwards; not counted as owed
        self.assertEqual(self.staff.post(f"/api/invoices/{body['id']}/settle/", {"pay_method": "Cash"}, format="json").status_code, 400)
        self.assertEqual(self.staff.post(f"/api/invoices/{body['id']}/cancel/", {"reason": "x"}, format="json").status_code, 400)
        dash = client_for(make_user("owner", superuser=True)).get("/api/dashboard/summary/").json()
        self.assertEqual(dash["pending_collections"], 0)

    def test_paid_invoice_cannot_be_cancelled(self):
        inv_id = self.sell([{"variant": self.b.id, "qty": 1, "price": 1}]).json()["id"]
        self.staff.post(f"/api/invoices/{inv_id}/settle/", {"pay_method": "Cash"}, format="json")
        response = self.staff.post(f"/api/invoices/{inv_id}/cancel/", {"reason": "oops"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("refund", response.json()["detail"])

    def test_cancelled_rent_month_can_be_billed_again(self):
        rental = Rental.objects.create(party=self.party, product_label="x", monthly_fee=1500, start=date(2026, 1, 1),
                                       tenure_months=6, last_payment=date(2026, 1, 1), status=Rental.ACTIVE)
        url = f"/api/rentals/{rental.id}/raise-invoice/"
        first = Invoice.objects.get(code=self.staff.post(url, {"stock_point": self.shop.id}, format="json").json()["invoice_code"])
        self.assertEqual(first.due_date, date(2026, 1, 1))
        self.staff.post(f"/api/invoices/{first.id}/cancel/", {"reason": "Wrong amount"}, format="json")
        again = Invoice.objects.get(code=self.staff.post(url, {"stock_point": self.shop.id}, format="json").json()["invoice_code"])
        self.assertEqual(again.period_start, date(2026, 1, 1))
        self.assertNotEqual(again.code, first.code)

    def test_cancel_needs_permission(self):
        inv_id = self.sell([{"variant": self.b.id, "qty": 1, "price": 1}]).json()["id"]
        viewer = client_for(make_user("viewer", ["invoices.view"]))
        self.assertEqual(viewer.post(f"/api/invoices/{inv_id}/cancel/", {"reason": "x"}, format="json").status_code, 403)
