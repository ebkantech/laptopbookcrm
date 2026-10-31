from django.test import TestCase

from catalog.models import Part, PartStock, Product, Stock, StockPoint, Variant
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
        # Owner-role stock manager (it restocks the online channel too); the
        # plain staff account works at the shop, so it sees that store only.
        self.stock_manager = client_for(make_user("stock-manager", ["inventory.edit"], owner=True))
        self.any_staff = client_for(make_user("any-staff", stock_point=self.shop))

    def test_next_code_continues_after_highest_existing(self):
        self.assertEqual(next_code("VC-LAP", Product, "product_code"), "VC-LAP-0008")
        self.assertEqual(next_code("VC-ACC", Product, "product_code"), "VC-ACC-0001")

    def test_any_staff_can_browse_and_search_products(self):
        self.assertEqual(len(results(self.any_staff.get("/api/products/"))), 1)
        self.assertEqual(len(results(self.any_staff.get("/api/products/", {"q": "thinkpad"}))), 1)
        self.assertEqual(len(results(self.any_staff.get("/api/products/", {"q": "macbook"}))), 0)
        # store-scoped: only the account's own shop, not the online channel
        self.assertEqual(len(results(self.any_staff.get("/api/stock-points/"))), 1)

    def test_lookup_by_product_or_variant_code(self):
        self.assertEqual(self.any_staff.get("/api/products/lookup/", {"code": "vc-sku-0003"}).json()["id"], self.product.id)
        self.assertEqual(self.any_staff.get("/api/products/lookup/", {"code": "VC-LAP-0007"}).json()["id"], self.product.id)
        self.assertEqual(self.any_staff.get("/api/products/lookup/", {"code": "NOPE"}).status_code, 404)
        self.assertEqual(self.any_staff.get("/api/products/lookup/").status_code, 400)

    def test_low_stock_lists_variants_with_four_or_fewer_units(self):
        # counted at the account's own store: 2 at the shop (the web's 1 isn't theirs)
        rows = self.any_staff.get("/api/products/low-stock/").json()
        self.assertEqual([(r["variant_code"], r["total_stock"]) for r in rows], [("VC-SKU-0003", 2)])

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
        new_spec_no_price = self.stock_manager.post("/api/inventory/add-stock/", {
            "stock_point": self.shop.id, "product": self.product.id, "spec": "i7 / 32GB", "quantity": 1,
        }, format="json")
        self.assertEqual(new_spec_no_price.status_code, 400)

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
        self.stock_manager = client_for(make_user("stock-manager", ["inventory.edit"], stock_point=self.shop))
        self.any_staff = client_for(make_user("any-staff", stock_point=self.shop))

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


class AddStockWithoutVariantsTests(TestCase):
    """Variants are optional: a restock without one still lands somewhere sensible."""

    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.stock_manager = client_for(make_user("stock-manager", ["inventory.edit"], stock_point=self.shop))
        self.url = "/api/inventory/add-stock/"

    def test_product_with_no_variants_gets_a_default_one(self):
        product = Product.objects.create(brand="\u2014", model_name="USB-C charger", product_code="VC-ACC-0001")
        response = self.stock_manager.post(self.url, {
            "stock_point": self.shop.id, "product": product.id, "quantity": 5,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["variant"]["spec"], body["new_quantity"]), ("Standard", 5))
        self.assertTrue(body["generated_variant_code"])

        # restocking again reuses that variant instead of making another
        again = self.stock_manager.post(self.url, {"stock_point": self.shop.id, "product": product.id, "quantity": 2}, format="json")
        self.assertEqual(again.json()["new_quantity"], 7)
        self.assertEqual(product.variants.count(), 1)

    def test_single_variant_is_used_automatically(self):
        product = Product.objects.create(model_name="Mouse", product_code="VC-ACC-0002")
        only = Variant.objects.create(product=product, code="VC-SKU-0001", spec="Black", mrp=600, sell_price=500, cost=300)
        response = self.stock_manager.post(self.url, {"stock_point": self.shop.id, "product": product.id, "quantity": 3}, format="json")
        self.assertEqual(response.json()["variant"]["id"], only.id)

    def test_several_variants_must_be_picked(self):
        product = Product.objects.create(model_name="Laptop bag", product_code="VC-ACC-0003")
        for i, colour in enumerate(["Black", "Grey"], start=1):
            Variant.objects.create(product=product, code=f"VC-SKU-000{i}", spec=colour, mrp=1, sell_price=1, cost=1)
        response = self.stock_manager.post(self.url, {"stock_point": self.shop.id, "product": product.id, "quantity": 1}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_new_item_without_variant_details(self):
        response = self.stock_manager.post(self.url, {
            "stock_point": self.shop.id, "model_name": "HDMI cable", "sell_price": 299, "quantity": 10,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["variant"]["spec"], body["variant"]["sell_price"]), ("Standard", 299))

    def test_failed_request_does_not_leave_a_new_product_behind(self):
        response = self.stock_manager.post(self.url, {
            "stock_point": self.shop.id, "model_name": "Ghost item", "spec": "Big", "quantity": 1,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Product.objects.filter(model_name="Ghost item").exists())


class StoreLocatorTests(TestCase):
    """Read-only Store Locator endpoints: every figure is scoped to one stock point."""

    def setUp(self):
        from datetime import date

        from parties.models import Party
        from rentals.models import RentalAsset
        from repairs.models import RepairTicket
        from sales.models import Invoice, InvoiceItem

        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP, address="12 MG Road")
        self.web = StockPoint.objects.create(slug="test-web", name="Test Website", kind=StockPoint.ONLINE)
        product = Product.objects.create(brand="Lenovo", model_name="ThinkPad T14", product_code="VC-LAP-0007")
        self.variant = Variant.objects.create(
            product=product, code="VC-SKU-0003", spec="i7 / 16GB", mrp=60000, sell_price=55000, cost=45000
        )
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=2, location="Rack A")
        Stock.objects.create(variant=self.variant, stock_point=self.web, quantity=5)
        part = Part.objects.create(slug="kb", name="Keyboard")
        PartStock.objects.create(part=part, stock_point=self.shop, quantity=3)

        party = Party.objects.create(name="Private Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        RepairTicket.objects.create(code="RPR-1", party=party, brand="HP", model_name="Pavilion", stock_point=self.shop,
                                    issue="No boot", status=RepairTicket.DIAGNOSING, received=date.today())
        RepairTicket.objects.create(code="RPR-2", party=party, brand="HP", model_name="Envy", stock_point=self.web,
                                    issue="No boot", status=RepairTicket.DELIVERED, received=date.today())
        paid = Invoice.objects.create(code="INV-1", party=party, stock_point=self.shop, date=date.today(), status=Invoice.PAID)
        InvoiceItem.objects.create(invoice=paid, variant=self.variant, qty=1, price=55000)
        owed = Invoice.objects.create(code="INV-2", party=party, stock_point=self.shop, date=date.today(), status=Invoice.LINK_SENT)
        InvoiceItem.objects.create(invoice=owed, variant=self.variant, qty=1, price=1000)
        elsewhere = Invoice.objects.create(code="INV-3", party=party, stock_point=self.web, date=date.today(), status=Invoice.PAID)
        InvoiceItem.objects.create(invoice=elsewhere, variant=self.variant, qty=1, price=99)
        RentalAsset.objects.create(asset_tag="AST-1", serial_number="S-1", brand="Dell", model_name="Latitude",
                                   source_stock_point=self.shop)

        self.owner = client_for(make_user("locator-owner", superuser=True))
        self.any_staff = client_for(make_user("any-staff", stock_point=self.shop))
        self.full = client_for(make_user("full", ["repairs.view", "invoices.view", "rentals.view"], stock_point=self.shop))

    def test_summary_counts_units_per_stock_point(self):
        rows = {r["id"]: r for r in self.owner.get("/api/stock-points/summary/").json()}
        self.assertEqual((rows[self.shop.id]["product_units"], rows[self.shop.id]["part_units"]), (2, 3))
        self.assertEqual((rows[self.web.id]["product_units"], rows[self.web.id]["part_records"]), (5, 0))

    def test_locator_is_scoped_to_the_selected_stock_point(self):
        data = self.full.get(f"/api/stock-points/{self.shop.id}/locator/").json()
        self.assertEqual([(s["variant_code"], s["quantity"], s["location"]) for s in data["stock"]], [("VC-SKU-0003", 2, "Rack A")])
        self.assertNotIn("cost", data["stock"][0])
        self.assertEqual([(p["name"], p["quantity"]) for p in data["parts"]], [("Keyboard", 3)])
        self.assertEqual((data["repairs"]["total"], data["repairs"]["open"]), (1, 1))
        self.assertEqual((data["invoices"]["count"], data["invoices"]["collected"], data["invoices"]["outstanding"]), (2, 55000, 1000))
        self.assertEqual([a["asset_tag"] for a in data["rentals"]["assets"]], ["AST-1"])
        self.assertNotIn("Private Customer", str(data))

    def test_business_sections_follow_existing_view_permissions(self):
        data = self.any_staff.get(f"/api/stock-points/{self.shop.id}/locator/").json()
        self.assertEqual(len(data["stock"]), 1)
        for section in ("repairs", "invoices", "rentals"):
            self.assertEqual(data[section], {"restricted": True})

    def test_store_staff_summary_and_detail_cover_only_their_store(self):
        rows = self.any_staff.get("/api/stock-points/summary/").json()
        self.assertEqual([r["id"] for r in rows], [self.shop.id])
        self.assertEqual(self.any_staff.get(f"/api/stock-points/{self.web.id}/locator/").status_code, 404)

    def test_unknown_stock_point_is_404(self):
        self.assertEqual(self.any_staff.get("/api/stock-points/999999/locator/").status_code, 404)
        self.assertEqual(self.any_staff.get("/api/stock-points/abc/locator/").status_code, 404)
