"""Stock leaving and returning to the shelf through a sale invoice's whole life:
sale, edit, cancel, refund, retries and two sales racing for the last units."""
import os
import threading
from datetime import date
from unittest import mock

from django.db import connection
from django.test import TestCase, TransactionTestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from sales.models import Invoice


class StockFixture:
    def make_fixture(self):
        self.staff = client_for(make_user(
            "stock-seller", ["invoices.view", "invoices.create", "invoices.settle", "invoices.refund"], owner=True,
        ))
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Buyer", type=Party.RETAIL, phone="9876543299", joined=date.today())
        product = Product.objects.create(brand="Dell", model_name="Latitude", product_code="P-STOCK-1")
        self.laptop = Variant.objects.create(product=product, code="V-LAP", spec="16GB", mrp=1, sell_price=40000, cost=1)
        self.charger = Variant.objects.create(product=product, code="V-CHG", spec="65W", mrp=1, sell_price=1500, cost=1)
        Stock.objects.create(variant=self.laptop, stock_point=self.kb, quantity=10)
        Stock.objects.create(variant=self.charger, stock_point=self.kb, quantity=6)
        Stock.objects.create(variant=self.laptop, stock_point=self.np, quantity=4)

    def shelf(self, variant, stock_point):
        return Stock.objects.get(variant=variant, stock_point=stock_point).quantity

    def sell(self, items, stock_point=None, client=None):
        return (client or self.staff).post("/api/invoices/", {
            "party": self.party.id, "stock_point": (stock_point or self.kb).id, "date": date.today().isoformat(), "items": items,
        }, format="json")


@mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"})
class SaleStockTests(StockFixture, TestCase):
    def setUp(self):
        self.make_fixture()

    def line(self, variant, qty, price=1000):
        return {"variant": variant.id, "qty": qty, "price": price}

    # -- 1, 2, 8: selling ----------------------------------------------
    def test_selling_3_of_10_leaves_7(self):
        response = self.sell([self.line(self.laptop, 3)])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.shelf(self.laptop, self.kb), 7)

    def test_each_product_on_a_multi_line_sale_loses_its_own_quantity(self):
        response = self.sell([self.line(self.laptop, 2), self.line(self.charger, 4), self.line(self.laptop, 1)])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((self.shelf(self.laptop, self.kb), self.shelf(self.charger, self.kb)), (7, 2))

    def test_a_sale_only_moves_the_shelf_it_was_sold_from(self):
        self.assertEqual(self.sell([self.line(self.laptop, 3)], self.np).status_code, 201)
        self.assertEqual((self.shelf(self.laptop, self.np), self.shelf(self.laptop, self.kb)), (1, 10))

    # -- 3, 4: never oversell ------------------------------------------
    def test_insufficient_stock_refuses_the_whole_invoice(self):
        response = self.sell([self.line(self.charger, 2), self.line(self.laptop, 11)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("only 10 in stock at Karol Bagh", response.json()["items"][0])
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual((self.shelf(self.laptop, self.kb), self.shelf(self.charger, self.kb)), (10, 6))

    def test_stock_never_goes_negative(self):
        self.assertEqual(self.sell([self.line(self.laptop, 10)]).status_code, 201)
        self.assertEqual(self.sell([self.line(self.laptop, 1)]).status_code, 400)
        self.assertEqual(self.shelf(self.laptop, self.kb), 0)

    # -- 5: retries never move stock twice -----------------------------
    def test_retried_cancel_settle_and_unchanged_edit_move_stock_once(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        url = f"/api/invoices/{invoice['id']}/"
        # resaving the same lines (a retried edit) moves nothing
        for _ in range(2):
            self.assertEqual(self.staff.patch(url, {"items": [self.line(self.laptop, 3)]}, format="json").status_code, 200)
        self.assertEqual(self.shelf(self.laptop, self.kb), 7)
        # a retried cancel is refused, so the units go back once
        self.assertEqual(self.staff.post(f"{url}cancel/", {"reason": "typo"}, format="json").status_code, 200)
        self.assertEqual(self.staff.post(f"{url}cancel/", {"reason": "typo"}, format="json").status_code, 400)
        self.assertEqual(self.shelf(self.laptop, self.kb), 10)

        paid = self.sell([self.line(self.laptop, 2)]).json()
        settle = {"pay_method": "Cash"}
        self.assertEqual(self.staff.post(f"/api/invoices/{paid['id']}/settle/", settle, format="json").status_code, 200)
        self.assertEqual(self.staff.post(f"/api/invoices/{paid['id']}/settle/", settle, format="json").status_code, 400)
        self.assertEqual(self.shelf(self.laptop, self.kb), 8)

    # -- 6: cancel restores --------------------------------------------
    def test_cancelling_a_sale_puts_every_line_back(self):
        invoice = self.sell([self.line(self.laptop, 3), self.line(self.charger, 2)]).json()
        self.assertEqual(self.staff.post(f"/api/invoices/{invoice['id']}/cancel/", {"reason": "wrong customer"}, format="json").status_code, 200)
        self.assertEqual((self.shelf(self.laptop, self.kb), self.shelf(self.charger, self.kb)), (10, 6))

    def test_partial_return_restocks_only_what_came_back(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        self.staff.post(f"/api/invoices/{invoice['id']}/settle/", {"pay_method": "Cash"}, format="json")
        refund = self.staff.post(f"/api/invoices/{invoice['id']}/refund/", {
            "method": "Cash", "reason": "one returned", "items": [{"item": invoice["items"][0]["id"], "qty": 1}],
        }, format="json")
        self.assertEqual(refund.status_code, 200, refund.content)
        self.assertEqual(self.shelf(self.laptop, self.kb), 8)

    # -- 7: edits move only the difference -----------------------------
    def test_editing_an_unpaid_sale_moves_only_the_difference(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        url = f"/api/invoices/{invoice['id']}/"
        response = self.staff.patch(url, {"items": [self.line(self.laptop, 5), self.line(self.charger, 1)]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["total"], 6000)
        self.assertEqual((self.shelf(self.laptop, self.kb), self.shelf(self.charger, self.kb)), (5, 5))

        self.assertEqual(self.staff.patch(url, {"items": [self.line(self.laptop, 1)]}, format="json").status_code, 200)
        self.assertEqual((self.shelf(self.laptop, self.kb), self.shelf(self.charger, self.kb)), (9, 6))

    def test_an_edit_beyond_the_shelf_is_refused_and_changes_nothing(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        # 3 already on this invoice + 7 left = 10 is fine; 11 is not
        response = self.staff.patch(f"/api/invoices/{invoice['id']}/", {"items": [self.line(self.laptop, 11)]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("only 7 in stock", response.json()["items"][0])
        self.assertEqual(self.shelf(self.laptop, self.kb), 7)
        self.assertEqual(Invoice.objects.get(pk=invoice["id"]).items.get().qty, 3)

    def test_moving_a_sale_to_another_shop_moves_its_stock(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        response = self.staff.patch(f"/api/invoices/{invoice['id']}/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((self.shelf(self.laptop, self.kb), self.shelf(self.laptop, self.np)), (10, 1))

    def test_paid_or_cancelled_sale_lines_cannot_be_edited(self):
        paid = self.sell([self.line(self.laptop, 2)]).json()
        self.staff.post(f"/api/invoices/{paid['id']}/settle/", {"pay_method": "Cash"}, format="json")
        cancelled = self.sell([self.line(self.laptop, 1)]).json()
        self.staff.post(f"/api/invoices/{cancelled['id']}/cancel/", {"reason": "typo"}, format="json")
        for invoice in (paid, cancelled):
            response = self.staff.patch(f"/api/invoices/{invoice['id']}/", {"items": [self.line(self.laptop, 5)]}, format="json")
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.shelf(self.laptop, self.kb), 8)

    def test_other_fields_still_edit_without_touching_stock(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        response = self.staff.patch(f"/api/invoices/{invoice['id']}/", {"recurring_interval": "monthly"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.shelf(self.laptop, self.kb), 7)

    def test_a_sale_invoice_cannot_be_deleted_out_from_under_its_stock(self):
        invoice = self.sell([self.line(self.laptop, 3)]).json()
        self.assertEqual(self.staff.delete(f"/api/invoices/{invoice['id']}/").status_code, 409)
        self.assertTrue(Invoice.objects.filter(pk=invoice["id"]).exists())
        self.assertEqual(self.shelf(self.laptop, self.kb), 7)


# -- 10: concurrency -- real transactions, so the row locks are real -----
@mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"})
class ConcurrentSaleTests(StockFixture, TransactionTestCase):
    def setUp(self):
        self.make_fixture()
        Stock.objects.filter(variant=self.laptop, stock_point=self.kb).update(quantity=5)

    def test_racing_sales_cannot_oversell(self):
        sellers = 4  # each wants 2 of the 5 units: only two can succeed
        start = threading.Barrier(sellers)
        statuses = []

        def sale():
            try:
                start.wait()
                statuses.append(self.sell([{"variant": self.laptop.id, "qty": 2, "price": 1}]).status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=sale) for _ in range(sellers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(statuses), [201, 201, 400, 400])
        self.assertEqual(self.shelf(self.laptop, self.kb), 1)
        self.assertEqual(Invoice.objects.count(), 2)
