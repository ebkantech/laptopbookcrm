"""Inventory -> Add stock -> Existing product: variants, colours, serials (catalog.new_product)."""
from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user

URL = "/api/inventory/add-stock/"


class ExistingProductTests(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.client_kb = client_for(make_user("stock-kb", ["inventory.edit"], stock_point=self.kb))
        self.product = Product.objects.create(brand="Dell", model_name="Latitude 5440", product_code="VC-LAP-0001",
                                              category="laptop", specs={"ram": "16GB"}, serial_tracking=True)
        self.black = Variant.objects.create(product=self.product, code="VC-SKU-0001", spec="i5 / 16GB", colour="Black",
                                            sell_price=50000, mrp=55000, cost=40000)
        Stock.objects.create(variant=self.black, stock_point=self.kb, quantity=3)
        Stock.objects.create(variant=self.black, stock_point=self.np, quantity=7)
        # created before categories and colours existed
        self.legacy = Product.objects.create(brand="HP", model_name="Old", product_code="VC-LAP-0002")
        self.plain = Variant.objects.create(product=self.legacy, code="VC-SKU-0002", spec="Imported", sell_price=100, mrp=100, cost=78)

    def post(self, client=None, **body):
        data = {"entry": "existing", "product": self.product.id, "stock_point": self.kb.id, "quantity": 2}
        data.update(body)
        return (client or self.client_kb).post(URL, data, format="json")

    def stock(self, variant, store):
        return Stock.objects.get(variant=variant, stock_point=store).quantity

    def test_case_a_same_colour_reuses_the_variant(self):
        response = self.post(variant=self.black.id, colour="  black ")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data["previous_quantity"], data["new_quantity"], data["created_variant"]), (3, 5, False))
        self.assertEqual((self.stock(self.black, self.kb), self.stock(self.black, self.np)), (5, 7))
        self.assertEqual(self.product.variants.count(), 1)

    def test_case_b_new_colour_is_a_new_variant_and_old_stock_untouched(self):
        response = self.post(new_variant=True, colour="Silver", spec="i5 / 16GB", sell_price=51000)
        self.assertEqual(response.status_code, 201, response.content)
        silver = Variant.objects.get(colour="Silver")
        self.assertEqual((silver.product, silver.spec, silver.sell_price, silver.mrp, silver.cost),
                         (self.product, "i5 / 16GB", 51000, 51000, 40000))
        self.assertNotEqual(silver.code, self.black.code)
        self.assertTrue(silver.code.startswith("VC-SKU-"))
        self.assertEqual(self.stock(silver, self.kb), 2)
        self.black.refresh_from_db()
        self.assertEqual((self.black.colour, self.black.spec, self.black.sell_price, self.stock(self.black, self.kb)),
                         ("Black", "i5 / 16GB", 50000, 3))
        self.assertEqual(Product.objects.filter(model_name="Latitude 5440").count(), 1)

    def test_selected_variant_is_never_recoloured(self):
        response = self.post(variant=self.black.id, colour="Silver")
        self.assertEqual(response.status_code, 400)
        self.assertIn("new colour", response.json()["colour"][0])
        legacy = self.post(product=self.legacy.id, variant=self.plain.id, colour="Grey")
        self.assertIn("no colour recorded", legacy.json()["colour"][0])
        self.assertEqual(self.stock(self.black, self.kb), 3)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.colour, "")

    def test_case_c_same_colour_other_spec_is_separate_and_exact_twin_refused(self):
        twin = self.post(new_variant=True, colour="BLACK", spec="i5 / 16gb", sell_price=50000)
        self.assertEqual(twin.status_code, 400)
        self.assertIn("Select that variant", twin.json()["variant"][0])
        other = self.post(new_variant=True, colour="Black", spec="i7 / 32GB", sell_price=70000)
        self.assertEqual(other.status_code, 201, other.content)
        self.assertEqual(self.product.variants.count(), 2)
        self.assertEqual(Variant.objects.get(spec="i7 / 32GB").cost, round(70000 * 0.78))

    def test_variant_choice_is_required_and_must_belong_to_the_product(self):
        self.assertIn("variant", self.post().json())
        self.assertIn("variant", self.post(variant=self.plain.id).json())
        self.assertIn("sell_price", self.post(new_variant=True, colour="Red").json())
        self.assertIn("product", self.post(product=99999).json())

    def test_prices_change_only_when_entered(self):
        self.post(variant=self.black.id)
        self.black.refresh_from_db()
        self.assertEqual((self.black.sell_price, self.black.mrp), (50000, 55000))
        response = self.post(variant=self.black.id, sell_price=52000)
        self.assertEqual(response.json()["price_changes"], {"sell_price": [50000, 52000]})
        self.assertIn("mrp", self.post(variant=self.black.id, sell_price=60000).json())  # above the current MRP

    def test_restock_generates_one_serial_per_unit(self):
        response = self.post(variant=self.black.id, quantity=4)
        self.assertEqual(response.status_code, 201, response.content)
        serials = response.json()["serials"]
        self.assertEqual(len(set(serials)), 4)
        self.assertTrue(all(s.startswith("DE") and len(s) == 7 for s in serials))  # "Dell Latitude 5440"
        self.assertEqual(StockSerial.objects.filter(variant=self.black, stock_point=self.kb).count(), 4)
        self.assertIn("serials", self.post(variant=self.black.id, serials=["X1"]).json())

    def test_restock_marks_an_old_product_as_carrying_serials(self):
        self.assertEqual(self.post(product=self.legacy.id, variant=self.plain.id).status_code, 201)
        self.legacy.refresh_from_db()
        self.assertTrue(self.legacy.serial_tracking)
        self.assertEqual(StockSerial.objects.filter(variant=self.plain).count(), 2)

    def test_uncategorised_product_restock_keeps_it_uncategorised(self):
        response = self.post(product=self.legacy.id, variant=self.plain.id)
        self.assertEqual(response.status_code, 201, response.content)
        self.legacy.refresh_from_db()
        self.assertEqual((self.legacy.category, self.legacy.model_name, self.legacy.specs), ("", "Old", {}))

    def test_store_scope_and_permission(self):
        self.assertEqual(self.post(variant=self.black.id, stock_point=self.np.id).status_code, 404)
        self.assertEqual(self.stock(self.black, self.np), 7)
        seller = client_for(make_user("seller", ["invoices.view"], stock_point=self.kb))
        self.assertEqual(self.post(client=seller, variant=self.black.id).status_code, 403)

    def test_search_by_serial_number_within_own_store(self):
        StockSerial.objects.create(variant=self.black, stock_point=self.kb, serial_number="FIND-ME-1", received_by=make_user("r1"))
        StockSerial.objects.create(variant=self.plain, stock_point=self.np, serial_number="FIND-ME-2", received_by=make_user("r2"))
        listed = self.client_kb.get("/api/products/", {"q": "find-me"}).json()
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual([r["id"] for r in rows], [self.product.id])  # the other store's serial isn't searchable here
        self.assertEqual(rows[0]["variants"][0]["colour"], "Black")

    def test_old_restock_request_still_works(self):
        response = self.client_kb.post(URL, {"product": self.product.id, "variant": self.black.id, "stock_point": self.kb.id, "quantity": 1}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.stock(self.black, self.kb), 4)

    def test_invoice_line_label_shows_colour(self):
        from sales.models import InvoiceItem
        self.assertEqual(InvoiceItem(variant=self.black, qty=1, price=1).label, "Dell Latitude 5440 (i5 / 16GB, Black)")
        self.assertEqual(InvoiceItem(variant=self.plain, qty=1, price=1).label, "HP Old (Imported)")


class ColourMigrationTests(TestCase):
    def test_colour_specification_is_copied_and_kept(self):
        import importlib

        from django.apps import apps
        migration = importlib.import_module("catalog.migrations.0006_variant_colour")
        product = Product.objects.create(model_name="Mouse", product_code="VC-ACC-0009", category="accessories",
                                         specs={"accessory_type": "Mouse", "colour": " Red "})
        blank = Variant.objects.create(product=product, code="VC-SKU-0091", spec="Mouse", sell_price=1, mrp=1, cost=1)
        named = Variant.objects.create(product=product, code="VC-SKU-0092", spec="Mouse", colour="Blue", sell_price=1, mrp=1, cost=1)
        migration.copy_colour_from_specs(apps, None)
        blank.refresh_from_db()
        named.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual((blank.colour, named.colour), ("Red", "Blue"))
        self.assertEqual(product.specs["colour"], " Red ")  # the saved specification is untouched

    def test_migration_only_adds(self):
        import importlib

        from django.db import migrations as m
        migration = importlib.import_module("catalog.migrations.0006_variant_colour").Migration
        add = next(op for op in migration.operations if isinstance(op, m.AddField))
        self.assertEqual((add.model_name, add.name, add.field.db_default), ("variant", "colour", ""))
        self.assertTrue(all(isinstance(op, (m.AddField, m.RunPython)) for op in migration.operations))
