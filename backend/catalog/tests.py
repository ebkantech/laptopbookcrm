from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from catalog.utils import next_code
from crmbook_backend.testing import client_for, make_user, results


class CatalogTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.web = StockPoint.objects.create(slug="test-web", name="Test Website", kind=StockPoint.ONLINE)
        self.product = Product.objects.create(brand="Lenovo", model_name="ThinkPad T14", product_code="VC-LAP-0007")
        self.variant = Variant.objects.create(
            product=self.product, code="VC-SKU-0003", spec="i7 / 16GB", mrp=60000, sell_price=55000, cost=45000
        )
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=2)
        Stock.objects.create(variant=self.variant, stock_point=self.web, quantity=1)
        self.stock_manager = client_for(make_user("stock-manager", ["inventory.edit"]))
        self.any_staff = client_for(make_user("any-staff"))

    def test_next_code_continues_after_highest_existing(self):
        self.assertEqual(next_code("VC-LAP", Product, "product_code"), "VC-LAP-0008")
        self.assertEqual(next_code("VC-ACC", Product, "product_code"), "VC-ACC-0001")

    def test_any_staff_can_browse_and_search_products(self):
        self.assertEqual(len(results(self.any_staff.get("/api/products/"))), 1)
        self.assertEqual(len(results(self.any_staff.get("/api/products/", {"q": "thinkpad"}))), 1)
        self.assertEqual(len(results(self.any_staff.get("/api/products/", {"q": "macbook"}))), 0)
        self.assertEqual(len(results(self.any_staff.get("/api/stock-points/"))), 2)

    def test_lookup_by_product_or_variant_code(self):
        self.assertEqual(self.any_staff.get("/api/products/lookup/", {"code": "vc-sku-0003"}).json()["id"], self.product.id)
        self.assertEqual(self.any_staff.get("/api/products/lookup/", {"code": "VC-LAP-0007"}).json()["id"], self.product.id)
        self.assertEqual(self.any_staff.get("/api/products/lookup/", {"code": "NOPE"}).status_code, 404)
        self.assertEqual(self.any_staff.get("/api/products/lookup/").status_code, 400)

    def test_low_stock_lists_variants_with_four_or_fewer_units(self):
        rows = self.any_staff.get("/api/products/low-stock/").json()
        self.assertEqual([(r["variant_code"], r["total_stock"]) for r in rows], [("VC-SKU-0003", 3)])

    def test_add_stock_to_existing_variant(self):
        response = self.stock_manager.post("/api/inventory/add-stock/", {
            "stock_point": self.shop.id, "product": self.product.id, "variant": self.variant.id, "quantity": 5,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["new_quantity"], 7)
        self.assertFalse(response.json()["generated_variant_code"])

    def test_add_stock_for_brand_new_item_generates_codes(self):
        response = self.stock_manager.post("/api/inventory/add-stock/", {
            "stock_point": self.web.id, "brand": "Dell", "model_name": "Inspiron 15",
            "spec": "i3 / 8GB", "sell_price": 32000, "quantity": 4,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["product"]["product_code"], "VC-LAP-0008")
        self.assertEqual(body["variant"]["code"], "VC-SKU-0004")
        self.assertEqual(body["variant"]["cost"], round(32000 * 0.78))
        self.assertEqual(body["new_quantity"], 4)

    def test_add_stock_validation(self):
        bad_qty = self.stock_manager.post("/api/inventory/add-stock/", {
            "stock_point": self.shop.id, "product": self.product.id, "variant": self.variant.id, "quantity": 0,
        }, format="json")
        self.assertEqual(bad_qty.status_code, 400)
        no_spec = self.stock_manager.post("/api/inventory/add-stock/", {
            "stock_point": self.shop.id, "product": self.product.id, "quantity": 1,
        }, format="json")
        self.assertEqual(no_spec.status_code, 400)

    def test_writes_need_inventory_edit(self):
        add = self.any_staff.post("/api/inventory/add-stock/", {
            "stock_point": self.shop.id, "product": self.product.id, "variant": self.variant.id, "quantity": 1,
        }, format="json")
        self.assertEqual(add.status_code, 403)
        create = self.any_staff.post("/api/products/", {"model_name": "X", "product_code": "VC-LAP-9999"}, format="json")
        self.assertEqual(create.status_code, 403)


class StockLocationTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        product = Product.objects.create(brand="Asus", model_name="VivoBook 15", product_code="VC-LAP-0001")
        self.variant = Variant.objects.create(
            product=product, code="VC-SKU-0001", spec="i5 / 8GB", mrp=45000, sell_price=40000, cost=32000
        )
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=2, location="Rack A / Shelf 1")
        self.stock_manager = client_for(make_user("stock-manager", ["inventory.edit"]))
        self.any_staff = client_for(make_user("any-staff"))

    def test_product_listing_shows_shop_name_and_location(self):
        stock = results(self.any_staff.get("/api/products/"))[0]["variants"][0]["stock"][0]
        self.assertEqual(
            (stock["stock_point_name"], stock["quantity"], stock["location"]),
            ("Test Shop", 2, "Rack A / Shelf 1"),
        )

    def test_add_stock_can_set_location_and_blank_keeps_existing(self):
        url = "/api/inventory/add-stock/"
        base = {"stock_point": self.shop.id, "product": self.variant.product_id, "variant": self.variant.id, "quantity": 1}
        self.assertEqual(self.stock_manager.post(url, base, format="json").json()["location"], "Rack A / Shelf 1")
        moved = self.stock_manager.post(url, {**base, "location": "Back store, bin 4"}, format="json").json()
        self.assertEqual((moved["location"], moved["new_quantity"]), ("Back store, bin 4", 4))

    def test_edit_location(self):
        url = f"/api/inventory/stock/{self.stock.id}/location/"
        response = self.stock_manager.patch(url, {"location": "  Rack C / Shelf 2 "}, format="json")
        self.assertEqual(response.status_code, 200)
        self.stock.refresh_from_db()
        self.assertEqual((self.stock.location, self.stock.quantity), ("Rack C / Shelf 2", 2))

        self.assertEqual(self.stock_manager.patch(url, {"location": ""}, format="json").status_code, 200)
        self.assertEqual(self.stock_manager.patch(url, {}, format="json").status_code, 400)
        self.assertEqual(self.stock_manager.patch(url, {"location": "x" * 81}, format="json").status_code, 400)
        self.assertEqual(self.any_staff.patch(url, {"location": "Rack Z"}, format="json").status_code, 403)
