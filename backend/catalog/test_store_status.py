from datetime import date

from django.test import TestCase

from catalog.models import Product, Service, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Party
from rentals.models import Rental, RentalAsset, RentalLine
from repairs.models import RepairTicket
from sales.models import Invoice

WORK = ["invoices.view", "invoices.create", "invoices.settle", "repairs.view", "repairs.manage",
        "inventory.edit", "rentals.view", "rentals.manage"]


class StoreStatusTests(TestCase):
    """
    Active / Inactive shops and channels (catalog.status): who may see and
    change it, which NEW operations an inactive stock point refuses, and that
    existing records and follow-up actions are untouched.
    """

    def setUp(self):
        self.shop = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Customer", type=Party.RETAIL, phone="9876500000", joined=date.today())
        product = Product.objects.create(brand="Dell", model_name="Latitude", product_code="VC-LAP-0001")
        self.variant = Variant.objects.create(product=product, code="VC-SKU-0001", spec="i5", mrp=50000, sell_price=40000, cost=30000)
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=5, location="Rack A")
        Stock.objects.create(variant=self.variant, stock_point=self.other, quantity=5)
        self.service = Service.objects.create(slug="screen", label="Screen", segment=Service.HARDWARE, charge=6000)

        self.root = client_for(make_user("root", superuser=True))
        self.owner = client_for(make_user("owner-admin", WORK, owner=True))
        # an "Admin" (roles.manage) assigned to Karol Bagh -- reaches that store only
        self.store_admin = client_for(make_user("store-admin", ["roles.manage", *WORK], stock_point=self.shop))
        self.seller_user = make_user("seller", WORK, stock_point=self.shop)
        self.seller = client_for(self.seller_user)

    # -- helpers --------------------------------------------------------
    def set_status(self, client, sp, value):
        return client.post(f"/api/stock-points/{sp.id}/set-status/", {"is_active": value}, format="json")

    def deactivate(self, sp=None):
        response = self.set_status(self.root, sp or self.shop, False)
        self.assertEqual(response.status_code, 200, response.content)

    def sell(self, client=None, sp=None):
        return (client or self.root).post("/api/invoices/", {
            "party": self.party.id, "stock_point": (sp or self.shop).id, "date": date.today().isoformat(),
            "items": [{"variant": self.variant.id, "qty": 1, "price": 40000}],
        }, format="json")

    def book_ticket(self, client=None, sp=None, serial="SN-1"):
        return (client or self.root).post("/api/tickets/", {
            "party": self.party.id, "brand": "Dell", "model_name": "Inspiron", "serial": serial,
            "stock_point": (sp or self.shop).id, "issue": "No boot", "service_ids": [self.service.id],
            "received": date.today().isoformat(),
        }, format="json")

    def rental(self):
        rental = Rental.objects.create(
            party=self.party, agreement_code="RNT-000900", product_label="1 device", monthly_fee=2000,
            start=date.today(), tenure_months=3, last_payment=date.today(), status=Rental.ACTIVE,
        )
        asset = RentalAsset.objects.create(asset_tag="AST-1", serial_number="SN-A1", brand="Dell", model_name="Latitude")
        RentalLine.objects.create(rental=rental, asset=asset, monthly_fee=2000)
        return rental

    def assert_inactive_refusal(self, response, field="stock_point"):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("is inactive", str(response.json()[field]))

    # 1 + 2. who can change it ----------------------------------------
    def test_superuser_deactivates_and_reactivates_the_same_record(self):
        response = self.set_status(self.root, self.shop, False)
        self.assertEqual((response.status_code, response.json()["id"], response.json()["is_active"]), (200, self.shop.id, False))
        self.shop.refresh_from_db()
        self.assertFalse(self.shop.is_active)
        self.assertEqual(self.set_status(self.root, self.shop, True).json()["is_active"], True)
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)
        self.assertEqual(StockPoint.objects.count(), 2)

    def test_owner_and_store_admin_can_change_status_within_their_scope(self):
        self.assertEqual(self.set_status(self.owner, self.other, False).status_code, 200)
        self.assertEqual(self.set_status(self.owner, self.other, True).status_code, 200)
        self.assertEqual(self.set_status(self.store_admin, self.shop, False).status_code, 200)
        self.assertEqual(self.set_status(self.store_admin, self.shop, True).status_code, 200)
        # another store is outside a store admin's scope
        self.assertEqual(self.set_status(self.store_admin, self.other, False).status_code, 404)
        self.other.refresh_from_db()
        self.assertTrue(self.other.is_active)

    def test_bad_body_is_rejected(self):
        self.assertEqual(self.set_status(self.root, self.shop, "no").status_code, 400)

    # 3. other roles: no status, no change --------------------------------
    def test_other_roles_get_403_and_never_see_status(self):
        self.assertEqual(self.set_status(self.seller, self.shop, False).status_code, 403)
        auditor = client_for(make_user("auditor", ["invoices.view", "reports.export"], stock_point=self.shop))
        self.assertEqual(self.set_status(auditor, self.shop, False).status_code, 403)
        # 403 even for a store outside their scope -- the role check comes first
        self.assertEqual(self.set_status(self.seller, self.other, False).status_code, 403)
        # editing the store can't flip it either
        self.assertEqual(self.seller.patch(f"/api/stock-points/{self.shop.id}/", {"is_active": False}, format="json").status_code, 403)
        self.shop.refresh_from_db()
        self.assertTrue(self.shop.is_active)

        listed = results(self.seller.get("/api/stock-points/"))
        self.assertNotIn("is_active", listed[0])
        self.assertNotIn("is_active", self.seller.get(f"/api/stock-points/{self.shop.id}/").json())
        self.assertNotIn("is_active", self.seller.get(f"/api/stock-points/{self.shop.id}/locator/").json()["stock_point"])
        self.assertNotIn("is_active", self.seller.get("/api/stock-points/inventory/").json()["stock_points"][0])
        self.assertFalse(self.seller.get("/api/users/me/").json()["can_manage_store_status"])

    def test_administrators_see_status(self):
        self.deactivate()
        rows = {r["id"]: r["is_active"] for r in results(self.root.get("/api/stock-points/"))}
        self.assertEqual(rows, {self.shop.id: False, self.other.id: True})
        self.assertIs(self.store_admin.get(f"/api/stock-points/{self.shop.id}/locator/").json()["stock_point"]["is_active"], False)
        for client in (self.root, self.owner, self.store_admin):
            self.assertTrue(client.get("/api/users/me/").json()["can_manage_store_status"])

    def test_owners_store_edit_cannot_set_status(self):
        # is_active only changes through set-status (audited, own permission)
        self.root.patch(f"/api/stock-points/{self.shop.id}/", {"is_active": False, "name": "KB"}, format="json")
        self.shop.refresh_from_db()
        self.assertEqual((self.shop.name, self.shop.is_active), ("KB", True))

    # 8 + 9. counts / selection lists --------------------------------------
    def test_active_filter_leaves_inactive_stock_points_out_of_new_operation_lists(self):
        self.deactivate()
        self.assertEqual([p["id"] for p in results(self.root.get("/api/stock-points/", {"active": "1"}))], [self.other.id])
        # the full list (history, filters) still has both
        self.assertEqual(len(results(self.root.get("/api/stock-points/"))), 2)
        # store staff of an inactive store: nothing to pick for new work, but their store still opens
        self.assertEqual(results(self.seller.get("/api/stock-points/", {"active": "1"})), [])
        self.assertEqual(self.seller.get(f"/api/stock-points/{self.shop.id}/locator/").status_code, 200)

    # 4 + 5 + 6. new operations ---------------------------------------------
    def test_new_sale_is_refused_then_allowed_after_reactivation(self):
        self.deactivate()
        self.assert_inactive_refusal(self.sell())
        self.assert_inactive_refusal(self.sell(client=self.seller))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 5)  # nothing taken off
        self.assertEqual(self.sell(sp=self.other).status_code, 201)  # other shop unaffected
        self.set_status(self.root, self.shop, True)
        self.assertEqual(self.sell(client=self.seller).status_code, 201)

    def test_new_repair_ticket_and_order_are_refused_then_allowed(self):
        self.deactivate()
        self.assert_inactive_refusal(self.book_ticket())
        order = {
            "party": self.party.id, "stock_point": self.shop.id, "received": date.today().isoformat(),
            "devices": [{"brand": "HP", "model_name": "X", "serial": "B-1", "issue": "x", "service_ids": [self.service.id]}],
        }
        self.assert_inactive_refusal(self.root.post("/api/repair-orders/", order, format="json"))
        self.assertFalse(RepairTicket.objects.exists())
        self.assertEqual(self.book_ticket(sp=self.other, serial="SN-O").status_code, 201)
        self.set_status(self.root, self.shop, True)
        self.assertEqual(self.book_ticket().status_code, 201)
        self.assertEqual(self.root.post("/api/repair-orders/", order, format="json").status_code, 201)

    def test_stock_in_and_out_is_refused_at_an_inactive_shop(self):
        self.deactivate()
        add = {"stock_point": self.shop.id, "product": self.variant.product_id, "variant": self.variant.id, "quantity": 2}
        self.assert_inactive_refusal(self.root.post("/api/inventory/add-stock/", add, format="json"))
        self.assert_inactive_refusal(
            self.root.post("/api/rental-assets/from-inventory/", {"stock": self.stock.id, "serial_number": "SN-R"}, format="json"),
            field="stock",
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 5)
        self.assertEqual(self.root.post("/api/inventory/add-stock/", {**add, "stock_point": self.other.id}, format="json").status_code, 201)
        self.set_status(self.root, self.shop, True)
        self.assertEqual(self.root.post("/api/inventory/add-stock/", add, format="json").status_code, 201)

    def test_rental_return_to_stock_needs_an_active_destination(self):
        asset = self.root.post("/api/rental-assets/from-inventory/", {"stock": self.stock.id, "serial_number": "SN-R"}, format="json").json()
        self.deactivate()
        url = f"/api/rental-assets/{asset['id']}/return-to-inventory/"
        self.assert_inactive_refusal(self.root.post(url, {}, format="json"))  # defaults to the inactive source shop
        response = self.root.post(url, {"stock_point": self.other.id}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["returned_to"], self.other.id)

    def test_rent_invoice_cannot_be_issued_from_an_inactive_shop(self):
        rental = self.rental()
        self.deactivate()
        url = f"/api/rentals/{rental.id}/raise-invoice/"
        self.assert_inactive_refusal(self.root.post(url, {"stock_point": self.shop.id}, format="json"))
        self.assertEqual(self.root.post(url, {"stock_point": self.other.id}, format="json").status_code, 201)

    def test_no_new_staff_assignment_but_existing_ones_stay(self):
        self.deactivate()
        url = f"/api/users/{self.seller_user.id}/"
        newcomer = make_user("newcomer", WORK)
        self.assert_inactive_refusal(self.root.post(f"/api/users/{newcomer.id}/set-store/", {"stock_point": self.shop.id}, format="json"))
        self.assert_inactive_refusal(self.root.patch(f"/api/users/{newcomer.id}/", {"stock_point": self.shop.id}, format="json"))
        self.assert_inactive_refusal(self.root.post("/api/users/", {"username": "fresh", "first_name": "Fresh", "stock_point": self.shop.id}, format="json"))
        # a store admin adding staff lands them in the admin's own (inactive) store -- refused too
        response = self.store_admin.post("/api/users/", {"username": "fresh2", "first_name": "Fresh"}, format="json")
        self.assert_inactive_refusal(response)
        # the staff already there keep their store, and can still be edited
        self.assertEqual(self.root.patch(url, {"first_name": "Renamed"}, format="json").status_code, 200)
        self.assertEqual(self.root.patch(url, {"first_name": "Renamed", "stock_point": self.shop.id}, format="json").status_code, 200)
        self.seller_user.refresh_from_db()
        self.assertEqual((self.seller_user.stock_point_id, self.seller_user.is_active), (self.shop.id, True))
        # moving them to an active shop is fine
        self.assertEqual(self.root.post(f"/api/users/{newcomer.id}/set-store/", {"stock_point": self.other.id}, format="json").status_code, 200)

    # 7. existing records & their follow-up actions --------------------------
    def test_existing_records_and_follow_up_actions_are_untouched(self):
        invoice_id = self.sell().json()["id"]
        ticket_id = self.book_ticket().json()["id"]
        before = self.root.get(f"/api/stock-points/{self.shop.id}/locator/").json()
        self.deactivate()

        # settle an existing invoice raised there
        settle = self.seller.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(settle.status_code, 200, settle.content)
        # update an existing repair ticket there, keeping its shop
        patch = self.seller.patch(f"/api/tickets/{ticket_id}/", {"issue": "No boot, fan noise", "stock_point": self.shop.id}, format="json")
        self.assertEqual(patch.status_code, 200, patch.content)
        # ...but it can't be moved INTO an inactive shop from elsewhere
        other_ticket = self.book_ticket(sp=self.other, serial="SN-O").json()["id"]
        self.assert_inactive_refusal(self.root.patch(f"/api/tickets/{other_ticket}/", {"stock_point": self.shop.id}, format="json"))
        # re-shelving existing stock isn't a stock movement
        self.assertEqual(self.seller.patch(f"/api/inventory/stock/{self.stock.id}/location/", {"location": "Rack B"}, format="json").status_code, 200)

        # history is all still there and readable
        self.assertEqual(Invoice.objects.get(pk=invoice_id).stock_point_id, self.shop.id)
        self.assertEqual(self.seller.get(f"/api/invoices/{invoice_id}/").json()["stock_point_name"], "Karol Bagh")
        self.assertEqual(self.seller.get(f"/api/tickets/{ticket_id}/").json()["stock_point_name"], "Karol Bagh")
        report = self.root.get("/api/reports/sales-summary/")
        self.assertEqual(report.status_code, 200, report.content)
        locator = self.root.get(f"/api/stock-points/{self.shop.id}/locator/").json()
        # the sale + the ticket's advance invoice, and the ticket -- same as before deactivating
        self.assertEqual(locator["invoices"]["count"], before["invoices"]["count"])
        self.assertEqual(locator["invoices"]["count"], 2)
        self.assertEqual(locator["repairs"]["total"], before["repairs"]["total"])
        self.assertEqual([s["quantity"] for s in locator["stock"]], [4])
        self.assertEqual(sorted(s["username"] for s in locator["staff"]), ["seller", "store-admin"])
        self.assertTrue(StockPoint.objects.filter(pk=self.shop.pk).exists())
