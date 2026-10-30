"""Add stock: Product ID vs Variant SKU vs automatic Serial Numbers vs HSN (catalog.new_product)."""
import itertools
import re
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase

from catalog import new_product
from catalog.models import Product, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user
from rentals.models import RentalAsset

URL = "/api/inventory/add-stock/"
FORMAT = re.compile(r"^[A-Z]{2}[0-9]{5}$")


class SerialAndIdTestBase(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.user = make_user("stock-kb", ["inventory.edit"], stock_point=self.kb)
        self.client_kb = client_for(self.user)
        # an existing accessory code, so the next one continues the sequence
        Product.objects.create(model_name="Older", product_code="VC-ACC-1003")

    def new(self, client=None, **extra):
        body = {"category": "other", "brand": "", "model_name": "Laptop", "specs": {"unit": "Piece"}, "colour": "Black",
                "hsn": "1234567890", "stock_point": self.kb.id, "quantity": 10, "sell_price": 900}
        body.update(extra)
        return (client or self.client_kb).post(URL, body, format="json")


class AutomaticSerialTests(SerialAndIdTestBase):
    def test_quantity_one_gives_one_seven_character_serial(self):
        data = self.new(quantity=1).json()
        self.assertEqual(len(data["serials"]), 1)
        self.assertRegex(data["serials"][0], FORMAT)
        self.assertTrue(data["serials"][0].startswith("LA"))

    def test_quantity_ten_gives_ten_unique_serials_in_the_exact_format(self):
        data = self.new().json()
        serials = data["serials"]
        self.assertEqual((len(serials), len(set(serials))), (10, 10))
        for s in serials:
            self.assertRegex(s, FORMAT)
            self.assertEqual(len(s), 7)
            self.assertFalse(s.isdigit())
            self.assertNotRegex(s, r"[-\s]")
        product = Product.objects.get(model_name="Laptop")
        self.assertEqual(sorted(StockSerial.objects.filter(variant__product=product).values_list("serial_number", flat=True)), sorted(serials))

    def test_prefix_comes_from_the_product_name(self):
        self.assertEqual(new_product.serial_prefix("Dell Latitude"), "DE")
        self.assertEqual(new_product.serial_prefix("charger"), "CH")
        self.assertEqual(new_product.serial_prefix("5440 Pro"), "PR")
        self.assertIsNone(new_product.serial_prefix("X 1"))
        response = self.new(model_name="X1")
        self.assertEqual(response.status_code, 400)
        self.assertIn("two letters", " ".join(response.json()["model_name"]))
        self.assertFalse(Product.objects.filter(model_name="X1").exists())

    def test_different_products_can_share_the_two_letters(self):
        a = self.new(model_name="Laptop", quantity=3).json()["serials"]
        b = self.new(model_name="Lamp", quantity=3).json()["serials"]
        self.assertTrue(all(s.startswith("LA") for s in a + b))
        self.assertEqual(len(set(a) | set(b)), 6)

    def test_an_existing_serial_is_never_reused_case_insensitively(self):
        product = Product.objects.create(model_name="Old", product_code="VC-ACC-0001")
        variant = Variant.objects.create(product=product, code="VC-SKU-0001", spec="x", sell_price=1, mrp=1, cost=1)
        StockSerial.objects.create(variant=variant, stock_point=self.kb, serial_number="la00001", received_by=self.user)
        RentalAsset.objects.create(asset_tag="RA-1", serial_number="LA00002", brand="Dell", model_name="X")
        # the first draws hit both used numbers; they're redrawn
        draws = itertools.chain([1, 2, 1, 2], itertools.count(3))
        with mock.patch("catalog.new_product.secrets.randbelow", side_effect=lambda n: next(draws)):
            serials = self.new(quantity=2).json()["serials"]
        self.assertEqual(len(serials), 2)
        self.assertFalse({"LA00001", "LA00002"} & set(serials))
        self.assertEqual(StockSerial.objects.get(serial_number="la00001").variant, variant)  # untouched

    def test_concurrent_addition_taking_a_number_is_redrawn(self):
        """Another stock addition commits LA00007 between our check and our
        insert: the unique index refuses it and a fresh batch is drawn."""
        product = Product.objects.create(model_name="Other one", product_code="VC-ACC-0002")
        variant = Variant.objects.create(product=product, code="VC-SKU-0002", spec="x", sell_price=1, mrp=1, cost=1)
        real_taken = new_product._taken
        calls = {"n": 0}

        def blind_then_real(candidates):
            calls["n"] += 1
            if calls["n"] == 1:
                StockSerial.objects.create(variant=variant, stock_point=self.np, serial_number="LA00007", received_by=self.user)
                return set()  # the race: our check didn't see it
            return real_taken(candidates)

        draws = itertools.count(7)  # LA00007 first, then fresh numbers
        with mock.patch("catalog.new_product._taken", side_effect=blind_then_real), \
                mock.patch("catalog.new_product.secrets.randbelow", side_effect=lambda n: next(draws)):
            response = self.new(quantity=1)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotEqual(response.json()["serials"], ["LA00007"])
        self.assertEqual(StockSerial.objects.filter(serial_number="LA00007").count(), 1)

    def test_running_out_of_numbers_fails_cleanly(self):
        with mock.patch.object(new_product, "SERIAL_SPACE", 5):
            response = self.new(quantity=6)
        self.assertEqual(response.status_code, 400)
        self.assertIn("unused serial numbers", response.json()["quantity"][0])
        self.assertFalse(Product.objects.filter(model_name="Laptop").exists())

    def test_failed_allocation_leaves_nothing_behind(self):
        with mock.patch("catalog.models.StockSerial.objects.bulk_create", side_effect=IntegrityError("boom")):
            response = self.new(quantity=3)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("boom", response.content.decode())  # no internal error text
        self.assertFalse(Product.objects.filter(model_name="Laptop").exists())
        self.assertFalse(Stock.objects.exists())
        self.assertFalse(StockSerial.objects.exists())

    def test_existing_serials_stay_unchanged(self):
        self.new(quantity=2)
        before = list(StockSerial.objects.order_by("id").values_list("id", "serial_number", "variant_id", "stock_point_id"))
        product = Product.objects.get(model_name="Laptop")
        self.client_kb.post(URL, {"entry": "existing", "product": product.id, "variant": product.variants.get().id,
                                  "stock_point": self.kb.id, "quantity": 3}, format="json")
        after = list(StockSerial.objects.order_by("id").values_list("id", "serial_number", "variant_id", "stock_point_id"))
        self.assertEqual(after[:2], before)
        self.assertEqual(len(after), 5)

    def test_search_finds_a_generated_serial(self):
        serial = self.new(quantity=1).json()["serials"][0]
        rows = self.client_kb.get("/api/products/", {"q": serial}).json()
        rows = rows["results"] if isinstance(rows, dict) else rows
        self.assertEqual([r["model_name"] for r in rows], ["Laptop"])


class ProductIdAndHsnTests(SerialAndIdTestBase):
    def test_one_product_id_for_every_unit_variant_and_restock(self):
        response = self.new()
        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get(model_name="Laptop")
        self.assertEqual(product.product_code, "VC-ACC-1004")  # same format and sequence as before; generated once
        self.assertEqual(Stock.objects.get(variant__product=product).quantity, 10)
        black = product.variants.get()
        # another colour, then a restock: same Product ID and HSN, more serials
        self.client_kb.post(URL, {"entry": "existing", "product": product.id, "new_variant": True, "spec": black.spec,
                                  "colour": "White", "stock_point": self.kb.id, "quantity": 3, "sell_price": 900}, format="json")
        self.client_kb.post(URL, {"entry": "existing", "product": product.id, "variant": black.id,
                                  "stock_point": self.kb.id, "quantity": 2}, format="json")
        product.refresh_from_db()
        self.assertEqual((product.product_code, product.hsn), ("VC-ACC-1004", "1234567890"))
        self.assertEqual(Product.objects.filter(model_name="Laptop").count(), 1)
        self.assertFalse(Product.objects.filter(product_code="VC-ACC-1005").exists())
        units = StockSerial.objects.filter(variant__product=product).select_related("variant__product")
        self.assertEqual(units.count(), 15)
        self.assertEqual({u.variant.product.product_code for u in units}, {"VC-ACC-1004"})
        self.assertEqual({u.variant.product.hsn for u in units}, {"1234567890"})
        self.assertEqual(product.variants.count(), 2)  # SKUs differ; the Product ID doesn't

    def test_hsn_is_optional_and_exactly_ten_digits(self):
        self.assertEqual(self.new(hsn="").status_code, 201)
        self.assertEqual(Product.objects.get(model_name="Laptop").hsn, "")
        for bad in ("84713010", "12345678901", "12345abcde", "1234-56789"):
            self.assertIn("hsn", self.new(model_name=f"Lamp {bad}", hsn=bad).json(), bad)
        self.assertEqual(self.new(model_name="Lantern", hsn="12345 67890").status_code, 201)
        self.assertEqual(Product.objects.get(model_name="Lantern").hsn, "1234567890")

    def test_restock_keeps_hsn_when_blank_and_updates_only_when_valid(self):
        product = Product.objects.create(model_name="Router", product_code="VC-ACC-0050", hsn="85176290")  # older 8-digit HSN
        variant = Variant.objects.create(product=product, code="VC-SKU-0050", spec="x", sell_price=1, mrp=1, cost=1)

        def restock(**extra):
            return self.client_kb.post(URL, {"entry": "existing", "product": product.id, "variant": variant.id,
                                             "stock_point": self.kb.id, "quantity": 1, **extra}, format="json")

        self.assertEqual(restock().status_code, 201)
        product.refresh_from_db()
        self.assertEqual(product.hsn, "85176290")  # blank never erases it
        self.assertIn("hsn", restock(hsn="123").json())
        response = restock(hsn="8517629000")
        self.assertTrue(response.json()["hsn_updated"])
        product.refresh_from_db()
        self.assertEqual(product.hsn, "8517629000")

    def test_new_product_placed_at(self):
        self.new(location="Rack B / Shelf 2")
        self.assertEqual(Stock.objects.get(variant__product__model_name="Laptop").location, "Rack B / Shelf 2")
        self.new(model_name="Lamp", location="")
        self.assertEqual(Stock.objects.get(variant__product__model_name="Lamp").location, "")

    def test_product_serial_list_is_per_unit_and_store_scoped(self):
        self.new(quantity=2)
        product = Product.objects.get(model_name="Laptop")
        StockSerial.objects.create(variant=product.variants.get(), stock_point=self.np, serial_number="NP12345", received_by=self.user)
        data = self.client_kb.get(f"/api/products/{product.id}/serials/").json()
        self.assertEqual((data["product_code"], data["hsn"]), ("VC-ACC-1004", "1234567890"))
        self.assertEqual(len(data["serials"]), 2)  # not the other store's unit
        self.assertTrue(all(FORMAT.match(s["serial_number"]) for s in data["serials"]))
        owner = client_for(make_user("root", superuser=True))
        self.assertEqual(len(owner.get(f"/api/products/{product.id}/serials/").json()["serials"]), 3)

    def test_permissions_and_store_scope(self):
        self.assertEqual(self.new(stock_point=self.np.id).status_code, 404)
        seller = client_for(make_user("seller", ["invoices.view"], stock_point=self.kb))
        seller_user = seller.handler._force_user
        seller_user.is_staff = True  # is_staff is not inventory permission
        seller_user.save()
        self.assertEqual(self.new(client=seller).status_code, 403)
        self.assertFalse(StockSerial.objects.exists())
