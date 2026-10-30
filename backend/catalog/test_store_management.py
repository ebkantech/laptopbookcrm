from datetime import date

from django.test import TestCase

from accounts.models import User
from catalog.models import PartStock, Part, Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results


class StoreManagementTests(TestCase):
    """
    Creating / editing a stock point: the row is updated in place (same id),
    every linked record shows the new details through its existing FK, and
    only the Owner / Super Admin may write.
    """

    def setUp(self):
        from parties.models import Party
        from rentals.models import RentalAsset
        from repairs.models import RepairTicket
        from sales.models import Invoice, InvoiceItem

        self.shop = StockPoint.objects.create(slug="kb", name="Karol Bagh Store", kind=StockPoint.SHOP,
                                              address="12 Ajmal Khan Rd", phone="011-4000000")
        self.web = StockPoint.objects.create(slug="amazon", name="Amazon", kind=StockPoint.ONLINE)
        product = Product.objects.create(brand="Dell", model_name="Latitude 5420", product_code="VC-LAP-0001")
        self.variant = Variant.objects.create(product=product, code="VC-SKU-0001", spec="i5 / 8GB",
                                              mrp=40000, sell_price=35000, cost=30000)
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=4, location="Rack B")
        self.part_stock = PartStock.objects.create(part=Part.objects.create(slug="ssd", name="SSD"),
                                                   stock_point=self.shop, quantity=2)
        party = Party.objects.create(name="Customer", type=Party.RETAIL, phone="9876500000", joined=date.today())
        self.ticket = RepairTicket.objects.create(code="RPR-9", party=party, brand="HP", model_name="Pavilion",
                                                  stock_point=self.shop, issue="No boot", received=date.today())
        self.invoice = Invoice.objects.create(code="INV-9", party=party, stock_point=self.shop, date=date.today(),
                                              status=Invoice.PAID)
        InvoiceItem.objects.create(invoice=self.invoice, variant=self.variant, qty=1, price=35000)
        self.asset = RentalAsset.objects.create(asset_tag="AST-9", serial_number="S-9", brand="Dell",
                                                model_name="Latitude", source_stock_point=self.shop)

        self.owner_user = make_user("store-owner", superuser=True)
        self.owner = client_for(self.owner_user)
        self.role_owner = client_for(make_user("role-owner", owner=True))
        self.clerk_user = make_user("clerk", ["repairs.view", "invoices.view", "rentals.view", "roles.manage"],
                                    stock_point=self.shop)
        self.clerk = client_for(self.clerk_user)

    def edit(self, client=None, sp=None, **body):
        return (client or self.owner).patch(f"/api/stock-points/{(sp or self.shop).id}/", body, format="json")

    # 1. same id, same row
    def test_update_keeps_the_same_id_and_row(self):
        before = StockPoint.objects.count()
        response = self.edit(name="Karol Bagh Flagship", address="14 Ajmal Khan Rd\nNew Delhi 110005", phone="+91 98100 00000")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["id"], self.shop.id)
        self.assertEqual(StockPoint.objects.count(), before)
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.name, self.shop.slug), ("Karol Bagh Flagship", "kb"))
        self.assertEqual(self.shop.address, "14 Ajmal Khan Rd\nNew Delhi 110005")

    # 2 + 3. linked records keep their FK and show the new details
    def test_linked_records_show_the_new_details(self):
        self.edit(name="KB Flagship", address="New address")
        self.stock.refresh_from_db()
        self.part_stock.refresh_from_db()
        self.clerk_user.refresh_from_db()
        self.assertEqual((self.stock.stock_point_id, self.stock.quantity, self.stock.location), (self.shop.id, 4, "Rack B"))
        self.assertEqual((self.part_stock.stock_point_id, self.part_stock.quantity), (self.shop.id, 2))
        self.assertEqual(self.clerk_user.stock_point_id, self.shop.id)

        self.assertEqual(self.clerk.get("/api/users/me/").json()["stock_point_name"], "KB Flagship")
        self.assertEqual(self.clerk.get(f"/api/tickets/{self.ticket.id}/").json()["stock_point_name"], "KB Flagship")
        self.assertEqual(self.clerk.get(f"/api/invoices/{self.invoice.id}/").json()["stock_point_name"], "KB Flagship")
        self.assertEqual(self.clerk.get(f"/api/rental-assets/{self.asset.id}/").json()["source_stock_point_name"], "KB Flagship")
        locator = self.clerk.get(f"/api/stock-points/{self.shop.id}/locator/").json()
        self.assertEqual((locator["stock_point"]["name"], locator["stock_point"]["address"]), ("KB Flagship", "New address"))
        self.assertEqual([s["quantity"] for s in locator["stock"]], [4])
        self.assertEqual([s["name"] for s in locator["staff"]], ["clerk"])
        product = results(self.clerk.get("/api/products/"))[0]
        self.assertEqual(product["variants"][0]["stock"][0]["stock_point_name"], "KB Flagship")

    # 5. invoices have no store snapshot: the seller block is read live
    def test_invoice_seller_block_reads_the_current_store(self):
        self.edit(name="KB Flagship", address="New address", phone="011-4999999")
        seller = self.clerk.get(f"/api/invoices/{self.invoice.id}/print-data/").json()["seller"]
        self.assertEqual((seller["branch"], seller["address"], seller["phone"]), ("KB Flagship", "New address", "011-4999999"))

    # 4. permissions
    def test_store_staff_cannot_edit_or_create_even_their_own_store(self):
        self.assertEqual(self.edit(client=self.clerk, name="Hijacked").status_code, 403)
        self.assertEqual(self.edit(client=self.clerk, sp=self.web, name="Hijacked").status_code, 403)
        self.assertEqual(self.clerk.put(f"/api/stock-points/{self.shop.id}/", {"name": "X", "kind": "shop"}, format="json").status_code, 403)
        self.assertEqual(self.clerk.post("/api/stock-points/", {"name": "Rogue", "kind": "shop"}, format="json").status_code, 403)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.name, "Karol Bagh Store")
        self.assertFalse(StockPoint.objects.filter(name="Rogue").exists())

    def test_unassigned_staff_and_anonymous_are_refused(self):
        unassigned = client_for(make_user("nobody", ["roles.manage"]))
        self.assertEqual(self.edit(client=unassigned, name="X").status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.patch(f"/api/stock-points/{self.shop.id}/", {"name": "X"},
                                           content_type="application/json").status_code, 401)

    def test_no_delete_endpoint(self):
        self.assertEqual(self.owner.delete(f"/api/stock-points/{self.shop.id}/").status_code, 405)
        self.assertTrue(StockPoint.objects.filter(pk=self.shop.pk).exists())

    def test_owner_role_can_create_and_slug_is_generated(self):
        response = self.role_owner.post("/api/stock-points/", {
            "name": "  Lajpat   Nagar  ", "kind": "shop", "address": "Central Market\nNew Delhi 110024", "gstin": "07abcde1234f1z5",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data["name"], data["slug"], data["gstin"]), ("Lajpat Nagar", "lajpat-nagar", "07ABCDE1234F1Z5"))
        again = self.role_owner.post("/api/stock-points/", {"name": "Lajpat-Nagar", "kind": "shop"}, format="json")
        self.assertEqual(again.json()["slug"], "lajpat-nagar-2")

    # validation
    def test_slug_cannot_change_after_creation(self):
        response = self.edit(slug="karol-bagh")
        self.assertEqual(response.status_code, 400)
        self.assertIn("slug", response.json())
        self.assertEqual(self.edit(slug="kb", name="Same code").status_code, 200)

    def test_validation_messages(self):
        self.assertIn("name", self.edit(name="   ").json())
        self.assertIn("name", self.edit(name="amazon").json())  # case-insensitive duplicate
        self.assertIn("phone", self.edit(phone="call me").json())
        self.assertIn("gstin", self.edit(gstin="12345").json())
        self.assertIn("kind", self.edit(kind="warehouse").json())
        self.assertIn("slug", self.owner.post("/api/stock-points/", {"name": "N", "kind": "shop", "slug": "amazon"}, format="json").json())
        self.assertIn("slug", self.owner.post("/api/stock-points/", {"name": "N", "kind": "shop", "slug": "Bad Slug"}, format="json").json())

    def test_legacy_phone_and_gstin_do_not_block_other_edits(self):
        StockPoint.objects.filter(pk=self.shop.pk).update(phone="ext 22", gstin="OLD")
        response = self.edit(name="Renamed", phone="ext 22", gstin="OLD")
        self.assertEqual(response.status_code, 200, response.content)

    def test_shop_with_staff_or_repairs_cannot_become_online(self):
        response = self.edit(kind="online")
        self.assertEqual(response.status_code, 400)
        self.assertIn("kind", response.json())
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.kind, StockPoint.SHOP)
        empty = StockPoint.objects.create(slug="spare", name="Spare Shop", kind=StockPoint.SHOP)
        self.assertEqual(self.edit(sp=empty, kind="online").status_code, 200)
        self.assertEqual(self.edit(sp=self.web, kind="shop").status_code, 200)

    def test_store_scope_is_unchanged_after_an_edit(self):
        self.edit(name="KB Flagship")
        self.assertEqual([p["id"] for p in results(self.clerk.get("/api/stock-points/"))], [self.shop.id])
        self.assertEqual(self.clerk.get(f"/api/stock-points/{self.web.id}/").status_code, 404)
        self.assertEqual(User.objects.get(pk=self.clerk_user.pk).stock_point_id, self.shop.id)
