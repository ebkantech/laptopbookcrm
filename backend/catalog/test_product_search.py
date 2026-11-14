"""
Inventory product search (?q= on /api/products/), used by the Inventory list
and by Add stock's product picker. A name typed the way the list shows it --
"<brand> <model>" -- must find the product at every length, not only while
it still fits inside the brand.
"""
from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results


class ProductSearchTests(TestCase):
    def setUp(self):
        self.a = StockPoint.objects.create(slug="search-a", name="Search A", kind=StockPoint.SHOP)
        self.b = StockPoint.objects.create(slug="search-b", name="Search B", kind=StockPoint.SHOP)
        rows = [("Acer", "Aspire 7", "laptop"), ("Dell", "Latitude 5420", "laptop"), ("Dell", "Inspiron 15", "laptop"),
                ("—", "Wireless Mouse", "accessories"), ("Asus", "Vivobook 15", "laptop")]
        for n, (brand, model, category) in enumerate(rows):
            product = Product.objects.create(brand=brand, model_name=model, product_code=f"VC-S-{n:04d}", category=category)
            variant = Variant.objects.create(product=product, code=f"SKU-S-{n:04d}", spec="s", mrp=1, sell_price=1, cost=1)
            Stock.objects.create(variant=variant, stock_point=self.a, quantity=n)  # n = 0 keeps a zero-stock product
        self.owner = client_for(make_user("search-owner", ["inventory.view"], owner=True))
        self.staff_b = client_for(make_user("search-staff-b", ["inventory.view"], stock_point=self.b))

    def names(self, q, client=None, **extra):
        return sorted(p["display_name"] for p in results((client or self.owner).get("/api/products/", {"q": q, **extra})))

    def test_every_prefix_of_the_shown_name_finds_the_product(self):
        name = "Acer Aspire 7"
        for n in range(1, len(name) + 1):
            self.assertIn(name, self.names(name[:n]), f"typed {name[:n]!r}")
        self.assertEqual(self.names(name), [name])

    def test_full_and_partial_names_case_and_spaces(self):
        self.assertEqual(self.names("dell latitude"), ["Dell Latitude 5420"])
        self.assertEqual(self.names("DELL LATITUDE 5420"), ["Dell Latitude 5420"])
        self.assertEqual(self.names("  Dell Latitude 5420  "), ["Dell Latitude 5420"])
        self.assertEqual(self.names("Dell   Latitude"), ["Dell Latitude 5420"])  # pasted double space
        self.assertEqual(self.names("dell"), ["Dell Inspiron 15", "Dell Latitude 5420"])
        self.assertEqual(self.names("spire"), ["Acer Aspire 7"])
        self.assertEqual(self.names("no such laptop"), [])

    def test_a_product_without_a_brand_is_found_by_its_shown_name(self):
        self.assertEqual(self.names("wireless mouse"), ["Wireless Mouse"])

    def test_codes_still_match(self):
        self.assertEqual(self.names("VC-S-0001"), ["Dell Latitude 5420"])
        self.assertEqual(self.names("sku-s-0004"), ["Asus Vivobook 15"])

    def test_blank_or_spaces_lists_everything_including_zero_stock(self):
        every = ["Acer Aspire 7", "Asus Vivobook 15", "Dell Inspiron 15", "Dell Latitude 5420", "Wireless Mouse"]
        self.assertEqual(self.names(""), every)
        self.assertEqual(self.names("   "), every)

    def test_search_combines_with_category(self):
        self.assertEqual(self.names("dell latitude", category="laptop"), ["Dell Latitude 5420"])
        self.assertEqual(self.names("dell latitude", category="non-laptop"), [])

    def test_search_keeps_the_store_scope_of_stock(self):
        data = results(self.staff_b.get("/api/products/", {"q": "acer aspire"}))
        self.assertEqual([p["display_name"] for p in data], ["Acer Aspire 7"])
        self.assertEqual([s for v in data[0]["variants"] for s in v["stock"]], [])  # store A's stock isn't shown to B
