"""Inventory product-type filter, and store-scoped laptop rental from Inventory."""
from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from rentals.models import RentalAsset


class CategoryFilterAndStoreScopeTests(TestCase):
    def setUp(self):
        self.a = StockPoint.objects.create(slug="store-a", name="Store A", kind=StockPoint.SHOP)
        self.b = StockPoint.objects.create(slug="store-b", name="Store B", kind=StockPoint.SHOP)
        self.stock = {}
        for n, (category, label) in enumerate([("laptop", "Latitude"), ("laptop", "ThinkPad"), ("charger", "Charger 65W"),
                                               ("ssd", "NVMe SSD"), ("ram", "DDR4 8GB"), ("accessories", "Bag"), ("", "Old item")]):
            product = Product.objects.create(brand="X", model_name=label, product_code=f"VC-T-{n:04d}", category=category)
            variant = Variant.objects.create(product=product, code=f"VC-SKU-{n:04d}", spec="s", mrp=1, sell_price=1, cost=1)
            for shop in (self.a, self.b):
                self.stock[(label, shop.slug)] = Stock.objects.create(variant=variant, stock_point=shop, quantity=2)
        self.staff_a = client_for(make_user("staff-a", ["inventory.view", "rentals.view", "rentals.manage"], stock_point=self.a))
        self.staff_b = client_for(make_user("staff-b", ["inventory.view", "rentals.view", "rentals.manage"], stock_point=self.b))
        self.owner = client_for(make_user("boss", ["inventory.view", "rentals.view", "rentals.manage"], owner=True))

    def names(self, client, query=""):
        return sorted(p["model_name"] for p in results(client.get(f"/api/products/{query}")))

    def test_all_laptop_and_parts_filters(self):
        every = ["Bag", "Charger 65W", "DDR4 8GB", "Latitude", "NVMe SSD", "Old item", "ThinkPad"]
        self.assertEqual(self.names(self.owner), every)
        self.assertEqual(self.names(self.owner, "?category=laptop"), ["Latitude", "ThinkPad"])
        self.assertEqual(self.names(self.owner, "?category=non-laptop"), [n for n in every if n not in ("Latitude", "ThinkPad")])

    def test_category_combines_with_search(self):
        self.assertEqual(self.names(self.owner, "?category=laptop&q=think"), ["ThinkPad"])
        self.assertEqual(self.names(self.owner, "?category=non-laptop&q=think"), [])
        self.assertEqual(self.names(self.owner, "?category=non-laptop&q=ssd"), ["NVMe SSD"])

    def test_category_combines_with_the_store_in_view(self):
        data = results(self.staff_a.get("/api/products/?category=laptop"))
        shops = {s["stock_point"] for p in data for v in p["variants"] for s in v["stock"]}
        self.assertEqual(shops, {"store-a"})

    def test_rental_picker_data_is_limited_to_the_staff_members_store(self):
        for client, slug in ((self.staff_a, "store-a"), (self.staff_b, "store-b")):
            data = results(client.get("/api/products/?category=laptop"))
            self.assertEqual({s["stock_point"] for p in data for v in p["variants"] for s in v["stock"]}, {slug})

    def test_staff_cannot_rent_from_another_store_by_api(self):
        other = self.stock[("Latitude", "store-b")]
        response = self.staff_a.post("/api/rental-assets/from-inventory/", {"stock": other.id, "serial_number": "X-1"}, format="json")
        self.assertEqual(response.status_code, 403)
        other.refresh_from_db()
        self.assertEqual((other.quantity, RentalAsset.objects.count()), (2, 0))

    def test_staff_can_rent_a_laptop_from_their_own_store_but_not_a_part(self):
        mine = self.stock[("Latitude", "store-a")]
        ok = self.staff_a.post("/api/rental-assets/from-inventory/", {"stock": mine.id, "serial_number": "X-2"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        part = self.stock[("NVMe SSD", "store-a")]
        bad = self.staff_a.post("/api/rental-assets/from-inventory/", {"stock": part.id, "serial_number": "X-3"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_owner_keeps_multi_store_access(self):
        far = self.stock[("ThinkPad", "store-b")]
        response = self.owner.post("/api/rental-assets/from-inventory/", {"stock": far.id, "serial_number": "X-4"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
