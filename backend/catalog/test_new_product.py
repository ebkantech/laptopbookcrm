"""Inventory -> Add stock -> New product (catalog.new_product via AddStockView)."""
from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user
from rentals.models import RentalAsset

URL = "/api/inventory/add-stock/"

VALID_SPECS = {
    "laptop": {"processor": "Intel Core i5", "generation": "12th Gen", "ram": "16GB", "storage": "512GB SSD", "screen_size": "15.6\""},
    "charger": {"wattage": "65W", "connector_type": "USB-C", "output_voltage": "20V", "compatibility": "Dell, HP"},
    "ssd": {"capacity": "1TB", "interface": "NVMe", "form_factor": "M.2 2280"},
    "ram": {"capacity": "8GB", "ddr_type": "DDR4", "speed": "3200MHz", "form_factor": "SO-DIMM"},
    "accessories": {"accessory_type": "Mouse", "warranty": "6 months"},
    "other": {"variant_size": "Large", "unit": "Piece"},
}


class NewProductTests(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.user = make_user("stock-kb", ["inventory.edit"], stock_point=self.kb)
        self.client_kb = client_for(self.user)

    def payload(self, category="laptop", **extra):
        body = {"category": category, "brand": "Dell", "model_name": f"Model {category}", "description": "Fresh stock",
                "specs": dict(VALID_SPECS[category]), "colour": "Black", "stock_point": self.kb.id, "quantity": 2,
                "sell_price": 50000, "mrp": 55000}
        body.update(extra)
        return body

    def post(self, body, client=None):
        return (client or self.client_kb).post(URL, body, format="json")

    def test_every_category_creates_product_variant_and_store_stock(self):
        for category in VALID_SPECS:
            response = self.post(self.payload(category))
            self.assertEqual(response.status_code, 201, (category, response.content))
            product = Product.objects.get(model_name=f"Model {category}")
            self.assertEqual((product.category, product.specs, product.description), (category, VALID_SPECS[category], "Fresh stock"))
            variant = product.variants.get()
            self.assertEqual((variant.sell_price, variant.mrp, variant.colour), (50000, 55000, "Black"))
            self.assertEqual(Stock.objects.get(variant=variant).stock_point, self.kb)
            self.assertEqual(Stock.objects.get(variant=variant).quantity, 2)
            self.assertTrue(product.product_code.startswith("VC-LAP" if category == "laptop" else "VC-ACC"))
        laptop = Product.objects.get(category="laptop")
        self.assertEqual(laptop.processor, "Intel Core i5")
        self.assertEqual(laptop.variants.get().spec, 'Intel Core i5 / 12th Gen / 16GB / 512GB SSD / 15.6"')
        self.assertEqual(Product.objects.get(category="charger").variants.get().spec, "65W / USB-C / 20V")

    def test_response_matches_the_existing_add_stock_shape(self):
        data = self.post(self.payload()).json()
        self.assertEqual((data["new_quantity"], data["stock_point"], data["serials_recorded"]), (2, "Karol Bagh", 2))
        self.assertEqual(len(data["serials"]), 2)
        self.assertEqual(data["product"]["category"], "laptop")
        self.assertEqual(data["product"]["specs"]["ram"], "16GB")

    def test_required_specs_per_category(self):
        response = self.post(self.payload("ssd", specs={"capacity": "1TB"}))
        self.assertEqual(response.status_code, 400)
        self.assertIn("specs.interface", response.json())
        response = self.post(self.payload("charger", brand="", specs={"wattage": "65W"}))
        self.assertTrue({"brand", "specs.connector_type"} <= set(response.json()))
        # brand is optional for Other
        self.assertEqual(self.post(self.payload("other", brand="")).status_code, 201)
        self.assertEqual(Product.objects.get(category="other").brand, "—")

    def test_irrelevant_and_invalid_specs_are_refused(self):
        response = self.post(self.payload("ram", specs={**VALID_SPECS["ram"], "wattage": "65W"}))
        self.assertIn("specs", response.json())
        response = self.post(self.payload("ssd", specs={**VALID_SPECS["ssd"], "interface": "IDE"}))
        self.assertIn("specs.interface", response.json())
        self.assertFalse(Product.objects.exists())

    def test_prices_and_quantity(self):
        self.assertIn("mrp", self.post(self.payload(sell_price=60000, mrp=55000)).json())
        self.assertEqual(self.post(self.payload(quantity=0)).status_code, 400)
        self.assertEqual(self.post(self.payload(sell_price=0)).status_code, 400)
        response = self.post(self.payload(mrp=None))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Variant.objects.get().mrp, 50000)  # no MRP given: the selling price, as before

    def test_serial_numbers_cannot_be_typed(self):
        response = self.post(self.payload(serials=["SN-001", "SN-002"]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("generated automatically", response.json()["serials"][0])
        self.assertFalse(Product.objects.exists())

    def test_colour_is_not_a_specification_any_more(self):
        response = self.post(self.payload("accessories", specs={**VALID_SPECS["accessories"], "colour": "Red"}))
        self.assertIn("specs", response.json())

    def test_same_product_in_another_colour_is_not_a_new_product(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        again = self.post(self.payload(colour="Silver"))
        self.assertEqual(again.status_code, 400)
        self.assertIn("Existing product", again.json()["model_name"][0])

    def test_duplicate_product_is_refused(self):
        self.assertEqual(self.post(self.payload()).status_code, 201)
        again = self.post(self.payload(brand="dell", model_name="model LAPTOP"))
        self.assertEqual(again.status_code, 400)
        self.assertIn("already in the catalogue", again.json()["model_name"][0])
        # a different specification is a different item
        other = self.post(self.payload(specs={**VALID_SPECS["laptop"], "ram": "32GB"}))
        self.assertEqual(other.status_code, 201, other.content)

    def test_store_scope_and_permissions(self):
        self.assertEqual(self.post(self.payload(stock_point=self.np.id)).status_code, 404)
        no_perm = client_for(make_user("seller", ["invoices.view"], stock_point=self.kb))
        self.assertEqual(self.post(self.payload(), client=no_perm).status_code, 403)
        unassigned = client_for(make_user("floating", ["inventory.edit"]))
        self.assertEqual(self.post(self.payload(), client=unassigned).status_code, 403)
        self.np.is_active = False
        self.np.save()
        owner = client_for(make_user("root", superuser=True))
        refused = self.post(self.payload(stock_point=self.np.id), client=owner)
        self.assertEqual(refused.status_code, 400)
        self.assertFalse(Product.objects.exists())

    def test_product_api_cannot_set_the_new_fields(self):
        self.post(self.payload())
        product = Product.objects.get()
        response = self.client_kb.patch(f"/api/products/{product.id}/", {"specs": {"x": "y"}, "category": "ram", "serial_tracking": True}, format="json")
        self.assertIn(response.status_code, (200, 403))
        product.refresh_from_db()
        self.assertEqual((product.category, product.serial_tracking), ("laptop", True))
        self.assertEqual(product.specs, VALID_SPECS["laptop"])

    def test_old_requests_still_work_unchanged(self):
        response = self.post({"brand": "HP", "model_name": "Legacy", "stock_point": self.kb.id, "quantity": 1, "sell_price": 20000, "spec": "Base"})
        self.assertEqual(response.status_code, 201, response.content)
        product = Product.objects.get(model_name="Legacy")
        self.assertEqual((product.category, product.specs, product.serial_tracking), ("", {}, False))

    def test_migration_only_adds_with_database_defaults(self):
        import importlib

        from django.db import migrations as m
        from django.db.models.fields import NOT_PROVIDED
        migration = importlib.import_module("catalog.migrations.0005_product_category_specs_serials").Migration
        for op in migration.operations:
            self.assertIsInstance(op, (m.AddField, m.CreateModel), op)
            if isinstance(op, m.AddField):
                self.assertIsNot(op.field.db_default, NOT_PROVIDED, op.name)
