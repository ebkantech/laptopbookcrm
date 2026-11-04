from datetime import date

from django.test import TestCase

from catalog.models import Product, SerialEvent, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from warranty.models import Warranty


class Base(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="shop", name="Main Shop", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="other", name="Other Shop", kind=StockPoint.SHOP)
        self.seller_user = make_user("seller", ["invoices.view", "invoices.create", "invoices.settle", "invoices.refund", "inventory.edit"], stock_point=self.shop)
        self.seller = client_for(self.seller_user)
        self.party = Party.objects.create(name="Buyer", type=Party.RETAIL, phone="9876543211", joined=date.today())
        self.product = Product.objects.create(brand="Dell", model_name="Latitude 5420", product_code="P-1", serial_tracking=True)
        self.v = Variant.objects.create(product=self.product, code="V-A", spec="16GB", mrp=1, sell_price=40000, cost=1)
        self.stock = Stock.objects.create(variant=self.v, stock_point=self.shop, quantity=3)
        self.units = [self.unit(f"LA0000{i}") for i in range(1, 4)]

    def unit(self, sn, sp=None, variant=None):
        u = StockSerial.objects.create(variant=variant or self.v, stock_point=sp or self.shop, serial_number=sn, received_by=self.seller_user)
        SerialEvent.objects.create(serial=u, event="received", text="Received", stock_point=u.stock_point)
        return u

    def sell(self, qty=1, serials=(), price=40000):
        return self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "items": [{"variant": self.v.id, "qty": qty, "price": price, "serials": list(serials)}],
        }, format="json")

    def status(self, sn):
        return StockSerial.objects.get(serial_number=sn).status


class SaleTests(Base):
    def test_sale_needs_the_units_serials_and_marks_them_sold(self):
        r = self.sell(1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("pick the serial number", " ".join(r.json()["items"]))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 3)  # nothing taken on a refused sale
        r = self.sell(2, ["la00001", "LA00002"])  # case-insensitive
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["items"][0]["serial_numbers"], ["LA00001", "LA00002"])
        self.assertEqual((self.status("LA00001"), self.status("LA00003")), ("sold", "in_stock"))
        self.assertTrue(SerialEvent.objects.filter(serial__serial_number="LA00001", event="sold").exists())

    def test_wrong_units_are_refused(self):
        self.unit("LA00009", sp=self.other)
        other_v = Variant.objects.create(product=self.product, code="V-B", spec="8GB", mrp=1, sell_price=1, cost=1)
        self.unit("LA00010", variant=other_v)
        self.sell(1, ["LA00001"])
        for bad, msg in (["LA00009", "Other Shop"], ["LA00010", "not a unit"], ["LA00001", "sold"], ["ZZ99999", "not a unit"]):
            r = self.sell(1, [bad])
            self.assertEqual(r.status_code, 400)
            self.assertIn(msg, " ".join(r.json()["items"]))

    def test_units_received_before_tracking_can_go_without_a_serial(self):
        StockSerial.objects.filter(serial_number="LA00003").delete()  # shelf 3, only 2 have serials
        self.assertEqual(self.sell(1).status_code, 201)       # the untracked unit
        self.assertEqual(self.sell(1).status_code, 400)       # none untracked left
        avail = self.seller.get(f"/api/stock-serials/available/?variant={self.v.id}&stock_point={self.shop.id}").json()
        self.assertEqual((avail["serials"], avail["untracked"]), (["LA00001", "LA00002"], 0))

    def test_cancelling_puts_the_units_back(self):
        inv = self.sell(1, ["LA00001"]).json()
        self.assertEqual(self.seller.post(f"/api/invoices/{inv['id']}/cancel/", {"reason": "Wrong item"}, format="json").status_code, 200)
        self.assertEqual(self.status("LA00001"), "in_stock")


class ReturnTests(Base):
    def paid(self, serials):
        inv = self.sell(len(serials), serials).json()
        self.seller.post(f"/api/invoices/{inv['id']}/settle/", {"pay_method": "Cash"}, format="json")
        return inv

    def refund(self, inv, qty, serials=None, restock=True):
        item = inv["items"][0]["id"]
        return self.seller.post(f"/api/invoices/{inv['id']}/refund/", {"method": "Cash", "reason": "Faulty",
                                "items": [{"item": item, "qty": qty, "serials": serials or []}], "restock": restock}, format="json")

    def test_return_names_the_unit_restock_or_not(self):
        inv = self.paid(["LA00001", "LA00002"])
        r = self.refund(inv, 1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("pick the serial number", r.json()["detail"])
        self.assertEqual(self.refund(inv, 1, ["LA00003"]).status_code, 400)  # never sold on this invoice
        self.assertEqual(self.refund(inv, 1, ["LA00002"]).status_code, 200)
        self.assertEqual(self.status("LA00002"), "in_stock")
        self.assertEqual(self.refund(inv, 1, ["LA00001"], restock=False).status_code, 200)
        self.assertEqual(self.status("LA00001"), "returned")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 2)  # 3 - 2 sold + 1 restocked


class WriteOffTraceWarrantyTests(Base):
    def test_write_off_with_and_without_reducing_stock(self):
        url = f"/api/stock-serials/{self.units[0].id}/write_off/"
        self.assertEqual(self.seller.post(url, {}, format="json").status_code, 400)  # reason required
        self.assertEqual(self.seller.post(url, {"reason": "Sold before tracking"}, format="json").status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual((self.status("LA00001"), self.stock.quantity), ("written_off", 3))
        self.seller.post(f"/api/stock-serials/{self.units[1].id}/write_off/", {"reason": "Dropped", "reduce_stock": True}, format="json")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 2)
        viewer = client_for(make_user("viewer", ["invoices.view"], stock_point=self.shop))
        self.assertEqual(viewer.post(f"/api/stock-serials/{self.units[2].id}/write_off/", {"reason": "x"}, format="json").status_code, 403)

    def test_trace_shows_sale_warranty_and_history(self):
        inv = self.sell(1, ["LA00001"]).json()
        self.seller.post(f"/api/invoices/{inv['id']}/settle/", {"pay_method": "Cash"}, format="json")
        w = Warranty.objects.get(invoice_id=inv["id"])  # auto-created on payment
        self.assertIn("S/N LA00001", w.item_label)
        t = self.seller.get("/api/stock-serials/trace/?q=la00001").json()
        self.assertEqual((t["status"], t["sale"]["invoice"], t["sale"]["customer"]), ("sold", inv["code"], "Buyer"))
        self.assertEqual([e["event"] for e in t["events"]], ["received", "sold"])
        self.assertEqual(len(t["warranties"]), 1)
        self.assertEqual(self.seller.get("/api/stock-serials/trace/?q=NOPE").status_code, 404)
        wl = self.seller.get("/api/warranties/?serial=LA00001").json()
        self.assertEqual(len(wl.get("results", wl)), 1)

    def test_other_store_cannot_trace_or_pick_our_units(self):
        theirs = client_for(make_user("theirs", ["invoices.view", "invoices.create"], stock_point=self.other))
        self.assertEqual(theirs.get("/api/stock-serials/trace/?q=LA00001").status_code, 404)
        self.assertEqual(theirs.get(f"/api/stock-serials/available/?variant={self.v.id}&stock_point={self.shop.id}").status_code, 403)


class RentalTests(Base):
    def test_renting_a_tracked_unit_needs_its_serial_and_returns_it(self):
        renter = client_for(make_user("renter", ["rentals.view", "rentals.manage"], owner=True))
        url = "/api/rental-assets/from-inventory/"
        self.assertEqual(renter.post(url, {"stock": self.stock.id, "serial_number": "C02XYZ"}, format="json").status_code, 400)
        r = renter.post(url, {"stock": self.stock.id, "serial_number": "LA00002"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.status("LA00002"), "rented")
        renter.post(f"/api/rental-assets/{r.json()['id']}/return-to-inventory/", {}, format="json")
        self.assertEqual(self.status("LA00002"), "in_stock")
