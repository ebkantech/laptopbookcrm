"""Putting a free rental device back on sale in Inventory."""
from datetime import date

from django.test import TestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from rentals.models import RentalAsset


class ReturnToInventoryTests(TestCase):
    def setUp(self):
        self.client_ = client_for(make_user("renter", ["rentals.view", "rentals.manage"]))
        self.shop = StockPoint.objects.create(slug="shop", name="Main Shop", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="other", name="Other Shop", kind=StockPoint.SHOP)
        product = Product.objects.create(model_name="ThinkPad T14", brand="Lenovo", product_code="P-1")
        self.variant = Variant.objects.create(product=product, code="V-1", spec="16GB", mrp=1, sell_price=1, cost=1)
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=1)

    def rent_from_inventory(self, serial="SN-RT-1"):
        response = self.client_.post("/api/rental-assets/from-inventory/", {"stock": self.stock.id, "serial_number": serial}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_back_to_the_shop_it_came_from_and_rented_out_again(self):
        asset = self.rent_from_inventory()
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 0)

        response = self.client_.post(f"/api/rental-assets/{asset['id']}/return-to-inventory/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["status"], response.json()["returned_to_name"]), ("retired", "Main Shop"))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 1)

        # renting the same unit again brings the old record back, not a duplicate
        again = self.rent_from_inventory()
        self.assertEqual((again["id"], again["status"]), (asset["id"], "available"))
        self.assertEqual(RentalAsset.objects.count(), 1)

    def test_to_another_shop(self):
        asset = self.rent_from_inventory()
        self.client_.post(f"/api/rental-assets/{asset['id']}/return-to-inventory/", {"stock_point": self.other.id}, format="json")
        self.assertEqual(Stock.objects.get(variant=self.variant, stock_point=self.other).quantity, 1)

    def test_only_free_inventory_devices(self):
        rented = RentalAsset.objects.create(asset_tag="AST-9", serial_number="SN-9", brand="Dell", model_name="X",
                                            status=RentalAsset.RENTED, variant=self.variant, source_stock_point=self.shop)
        self.assertIn("free device", self.client_.post(f"/api/rental-assets/{rented.id}/return-to-inventory/").json()["detail"])
        manual = RentalAsset.objects.create(asset_tag="AST-8", serial_number="SN-8", brand="Dell", model_name="X")
        self.assertIn("wasn't taken from Inventory", self.client_.post(f"/api/rental-assets/{manual.id}/return-to-inventory/").json()["detail"])
