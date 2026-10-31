"""
Store-level data isolation (accounts.store_scope): the Owner sees every
store; store-assigned staff only their own; unassigned staff none -- and
role permissions keep applying on top.
"""
from datetime import date

from django.test import TestCase

from accounting.models import BankAccount, CashEntry
from accounts.models import User
from catalog.models import Part, PartStock, Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Party
from rentals.models import Rental, RentalAsset, RentalLine
from repairs.models import RepairTicket
from sales.models import Invoice, InvoiceItem
from warranty.models import Warranty

ALL_VIEW = ["invoices.view", "repairs.view", "rentals.view", "cashbook.view", "bankbook.view", "parties.view", "reports.export", "inventory.edit"]


class StoreScopeFixture(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP, address="Ajmal Khan Road")
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.web = StockPoint.objects.create(slug="amazon", name="Amazon", kind=StockPoint.ONLINE)

        product = Product.objects.create(brand="Dell", model_name="Latitude 5420", product_code="VC-LAP-0001")
        self.variant = Variant.objects.create(product=product, code="VC-SKU-0001", spec="i5", mrp=50000, sell_price=45000, cost=40000)
        self.kb_stock = Stock.objects.create(variant=self.variant, stock_point=self.kb, quantity=3)
        self.np_stock = Stock.objects.create(variant=self.variant, stock_point=self.np, quantity=9)
        part = Part.objects.create(slug="kbd", name="Keyboard")
        PartStock.objects.create(part=part, stock_point=self.kb, quantity=2)
        PartStock.objects.create(part=part, stock_point=self.np, quantity=7)

        self.party = Party.objects.create(name="Shared Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        self.kb_invoice = self._invoice("INV-KB", self.kb, 45000, Invoice.PAID)
        self.np_invoice = self._invoice("INV-NP", self.np, 99000, Invoice.PAID)
        self.kb_ticket = RepairTicket.objects.create(code="RPR-KB", party=self.party, brand="HP", model_name="Pavilion",
                                                     stock_point=self.kb, issue="x", received=date.today())
        self.np_ticket = RepairTicket.objects.create(code="RPR-NP", party=self.party, brand="HP", model_name="Envy",
                                                     stock_point=self.np, issue="x", received=date.today())
        self.kb_rental = self._rental("RNT-KB", "SN-KB", self.kb)
        self.np_rental = self._rental("RNT-NP", "SN-NP", self.np)

        self.owner = client_for(make_user("owner", superuser=True))
        self.kb_user = make_user("kb-staff", ALL_VIEW + ["invoices.create", "invoices.settle", "repairs.manage", "rentals.manage", "cashbook.edit"], stock_point=self.kb)
        self.kb_staff = client_for(self.kb_user)
        self.pending_user = make_user("pending", ALL_VIEW)
        self.pending = client_for(self.pending_user)

    def _invoice(self, code, sp, amount, status):
        inv = Invoice.objects.create(code=code, party=self.party, stock_point=sp, date=date.today(), status=status)
        InvoiceItem.objects.create(invoice=inv, variant=self.variant, qty=1, price=amount)
        return inv

    def _rental(self, code, serial, sp):
        rental = Rental.objects.create(party=self.party, agreement_code=code, product_label="x", monthly_fee=1000,
                                       start=date.today(), tenure_months=6, last_payment=date.today())
        asset = RentalAsset.objects.create(asset_tag=f"AST-{serial}", serial_number=serial, brand="Dell", model_name="X",
                                           status=RentalAsset.RESERVED, source_stock_point=sp)
        rental.line = RentalLine.objects.create(rental=rental, asset=asset, monthly_fee=1000)
        return rental


class OwnerSeesEveryStoreTests(StoreScopeFixture):
    def test_superuser_sees_all_stock_points_and_records(self):
        self.assertEqual(len(results(self.owner.get("/api/stock-points/"))), 3)
        self.assertEqual({i["code"] for i in results(self.owner.get("/api/invoices/"))}, {"INV-KB", "INV-NP"})
        self.assertEqual({t["code"] for t in results(self.owner.get("/api/tickets/"))}, {"RPR-KB", "RPR-NP"})
        self.assertEqual(len(results(self.owner.get("/api/rentals/"))), 2)
        self.assertEqual(self.owner.get(f"/api/stock-points/{self.np.id}/locator/").status_code, 200)
        stock = results(self.owner.get("/api/products/"))[0]["variants"][0]
        self.assertEqual(stock["total_stock"], 12)

    def test_owner_role_account_sees_all_stores_but_keeps_its_role_permissions(self):
        owner_role = client_for(make_user("owner-role", ["invoices.view"], owner=True))
        self.assertEqual(len(results(owner_role.get("/api/invoices/"))), 2)
        self.assertEqual(owner_role.get("/api/tickets/").status_code, 403)  # role lacks repairs.view


class StoreStaffIsolationTests(StoreScopeFixture):
    def test_stock_points_and_locator_are_limited_to_own_store(self):
        self.assertEqual([sp["id"] for sp in results(self.kb_staff.get("/api/stock-points/"))], [self.kb.id])
        self.assertEqual(self.kb_staff.get(f"/api/stock-points/{self.np.id}/").status_code, 404)
        self.assertEqual(self.kb_staff.get(f"/api/stock-points/{self.np.id}/locator/").status_code, 404)
        self.assertEqual(self.kb_staff.get(f"/api/stock-points/{self.web.id}/locator/").status_code, 404)

    def test_karol_bagh_staff_cannot_see_nehru_place_inventory(self):
        variant = results(self.kb_staff.get("/api/products/"))[0]["variants"][0]
        self.assertEqual([s["stock_point"] for s in variant["stock"]], ["kb"])
        self.assertEqual(variant["total_stock"], 3)
        lookup = self.kb_staff.get("/api/products/lookup/", {"code": "VC-SKU-0001"}).json()
        self.assertEqual([s["stock_point"] for s in lookup["variants"][0]["stock"]], ["kb"])
        part = results(self.kb_staff.get("/api/parts/"))[0]
        self.assertEqual([(s["stock_point"], s["quantity"]) for s in part["stock"]], [("kb", 2)])
        self.assertEqual(self.kb_staff.patch(f"/api/inventory/stock/{self.np_stock.id}/location/", {"location": "x"}, format="json").status_code, 404)
        add = self.kb_staff.post("/api/inventory/add-stock/", {"stock_point": self.np.id, "product": self.variant.product_id,
                                                                "variant": self.variant.id, "quantity": 1}, format="json")
        self.assertEqual(add.status_code, 404)
        self.np_stock.refresh_from_db()
        self.assertEqual(self.np_stock.quantity, 9)

    def test_shared_product_can_only_be_edited_by_the_owner(self):
        url = f"/api/products/{self.variant.product_id}/"
        self.assertEqual(self.kb_staff.patch(url, {"model_name": "Renamed"}, format="json").status_code, 403)
        self.assertEqual(self.kb_staff.delete(url).status_code, 403)
        self.assertEqual(self.owner.patch(url, {"model_name": "Renamed"}, format="json").status_code, 200)

    def test_summary_does_not_reveal_other_stores_counts(self):
        rows = self.kb_staff.get("/api/stock-points/summary/").json()
        self.assertEqual([(r["id"], r["product_units"], r["part_units"]) for r in rows], [(self.kb.id, 3, 2)])
        sales = self.kb_staff.get("/api/reports/sales-summary/").json()
        self.assertEqual([r["name"] for r in sales["by_stock_point"]], ["Karol Bagh"])
        self.assertEqual(sales["total_revenue_paid"], 45000)
        stock = self.kb_staff.get("/api/reports/inventory-stock/").json()
        self.assertEqual((stock["total_stock_units"], [r["name"] for r in stock["by_stock_point"]]), (3, ["Karol Bagh"]))
        fin = self.kb_staff.get("/api/reports/financial-summary/").json()
        self.assertEqual(sum(m["revenue"] for m in fin["monthly_revenue"]), 45000)
        turnaround = self.kb_staff.get("/api/reports/repair-turnaround/").json()
        self.assertEqual(sum(turnaround["stage_counts"].values()), 1)
        party = self.kb_staff.get("/api/reports/party-report/").json()
        self.assertEqual(party["top_customers"][0]["total_spent"], 45000)

    def test_dashboard_is_pinned_to_own_store_whatever_channel_is_asked_for(self):
        dash = self.kb_staff.get("/api/dashboard/summary/", {"channel": "np"}).json()
        self.assertEqual(dash["filters_applied"]["channel"], "kb")
        self.assertEqual([c["name"] for c in dash["channel_sales"]], ["Karol Bagh"])
        self.assertEqual(dash["total_stock_units"], 3)
        self.assertEqual(sum(dash["repair_stage_counts"].values()), 1)

    def test_invoices_of_another_store_are_unreachable(self):
        self.assertEqual([i["code"] for i in results(self.kb_staff.get("/api/invoices/"))], ["INV-KB"])
        self.assertEqual(self.kb_staff.get(f"/api/invoices/{self.np_invoice.id}/").status_code, 404)
        self.assertEqual(self.kb_staff.get(f"/api/invoices/{self.np_invoice.id}/print-data/").status_code, 404)
        self.assertEqual(self.kb_staff.post(f"/api/invoices/{self.np_invoice.id}/cancel/", {"reason": "x"}, format="json").status_code, 404)

    def test_cannot_raise_or_move_an_invoice_to_another_store(self):
        body = {"party": self.party.id, "stock_point": self.np.id, "date": date.today().isoformat(),
                "items": [{"variant": self.variant.id, "qty": 1, "price": 1}]}
        self.assertEqual(self.kb_staff.post("/api/invoices/", body, format="json").status_code, 403)
        self.np_stock.refresh_from_db()
        self.assertEqual(self.np_stock.quantity, 9)
        moved = self.kb_staff.patch(f"/api/invoices/{self.kb_invoice.id}/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(moved.status_code, 403)
        ok = self.kb_staff.post("/api/invoices/", {**body, "stock_point": self.kb.id}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_repair_tickets_of_another_store_are_unreachable(self):
        self.assertEqual([t["code"] for t in results(self.kb_staff.get("/api/tickets/"))], ["RPR-KB"])
        self.assertEqual(self.kb_staff.get(f"/api/tickets/{self.np_ticket.id}/").status_code, 404)
        self.assertEqual(self.kb_staff.post(f"/api/tickets/{self.np_ticket.id}/set-stage/", {"status": "Diagnosing"}, format="json").status_code, 404)
        moved = self.kb_staff.patch(f"/api/tickets/{self.kb_ticket.id}/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(moved.status_code, 403)
        self.kb_ticket.refresh_from_db()
        self.assertEqual(self.kb_ticket.stock_point, self.kb)
        order = self.kb_staff.post("/api/repair-orders/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(order.status_code, 403)

    def test_rentals_assets_and_handover_follow_the_device_store(self):
        self.assertEqual([r["agreement_code"] for r in results(self.kb_staff.get("/api/rentals/"))], ["RNT-KB"])
        self.assertEqual(self.kb_staff.get(f"/api/rentals/{self.np_rental.id}/").status_code, 404)
        self.assertEqual({a["asset_tag"] for a in results(self.kb_staff.get("/api/rental-assets/"))}, {"AST-SN-KB"})
        self.assertEqual(self.kb_staff.get(f"/api/rental-lines/{self.np_rental.line.id}/handover/").status_code, 404)
        self.assertEqual(self.kb_staff.get(f"/api/rental-lines/{self.kb_rental.line.id}/handover/").status_code, 200)
        bill = self.kb_staff.post(f"/api/rentals/{self.kb_rental.id}/raise-invoice/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(bill.status_code, 403)

    def test_accounting_only_shows_entries_posted_from_own_store(self):
        CashEntry.objects.create(date=date.today(), particulars="KB sale", type=CashEntry.IN, amount=1, by=self.kb_user, invoice=self.kb_invoice)
        CashEntry.objects.create(date=date.today(), particulars="NP sale", type=CashEntry.IN, amount=1, by=self.kb_user, invoice=self.np_invoice)
        CashEntry.objects.create(date=date.today(), particulars="Rent", type=CashEntry.OUT, amount=1, by=self.kb_user)
        BankAccount.objects.create(name="HDFC")
        self.assertEqual([e["particulars"] for e in results(self.kb_staff.get("/api/cash-entries/"))], ["KB sale"])
        self.assertEqual(results(self.kb_staff.get("/api/bank-accounts/")), [])
        manual = self.kb_staff.post("/api/cash-entries/", {"date": date.today().isoformat(), "particulars": "x",
                                                            "type": CashEntry.IN, "amount": 1}, format="json")
        self.assertEqual(manual.status_code, 403)
        self.assertEqual(len(results(self.owner.get("/api/cash-entries/"))), 3)

    def test_warranties_and_customer_history_are_store_scoped(self):
        Warranty.objects.create(party=self.party, section=Warranty.SALES, invoice=self.np_invoice, item_label="x",
                                start_date=date.today(), end_date=date.today())
        self.assertEqual(results(self.kb_staff.get("/api/warranties/")), [])
        detail = self.kb_staff.get(f"/api/parties/{self.party.id}/").json()
        self.assertEqual([i["code"] for i in detail["invoices"]], ["INV-KB"])
        self.assertEqual(detail["total_spent"], 45000)

    def test_role_permissions_still_apply_inside_the_store(self):
        sales_only = client_for(make_user("kb-sales", ["invoices.view"], stock_point=self.kb))
        self.assertEqual(sales_only.get("/api/tickets/").status_code, 403)
        self.assertEqual(sales_only.get("/api/cash-entries/").status_code, 403)
        self.assertEqual(sales_only.post(f"/api/invoices/{self.kb_invoice.id}/settle/", {"pay_method": "Cash"}, format="json").status_code, 403)
        locator = sales_only.get(f"/api/stock-points/{self.kb.id}/locator/").json()
        self.assertEqual((locator["repairs"], locator["invoices"]["restricted"]), ({"restricted": True}, False))


class UnassignedStaffTests(StoreScopeFixture):
    def test_unassigned_staff_reach_no_store_at_all(self):
        self.assertEqual(results(self.pending.get("/api/stock-points/")), [])
        self.assertEqual(self.pending.get("/api/stock-points/summary/").json(), [])
        self.assertEqual(results(self.pending.get("/api/invoices/")), [])
        self.assertEqual(results(self.pending.get("/api/tickets/")), [])
        self.assertEqual(results(self.pending.get("/api/rentals/")), [])
        self.assertEqual(results(self.pending.get("/api/products/"))[0]["variants"][0]["stock"], [])
        self.assertEqual(self.pending.get(f"/api/invoices/{self.kb_invoice.id}/").status_code, 404)
        dash = self.pending.get("/api/dashboard/summary/").json()
        self.assertEqual((dash["store_scope"]["assigned"], set(dash["sections"].values())), (False, {False}))
        self.assertEqual(self.pending.get("/api/reports/sales-summary/").json()["by_stock_point"], [])

    def test_unassigned_staff_cannot_write_store_records(self):
        body = {"party": self.party.id, "stock_point": self.kb.id, "date": date.today().isoformat(),
                "items": [{"variant": self.variant.id, "qty": 1, "price": 1}]}
        writer = client_for(make_user("pending-writer", ["invoices.view", "invoices.create"]))
        self.assertEqual(writer.post("/api/invoices/", body, format="json").status_code, 403)


class StoreAssignmentTests(StoreScopeFixture):
    def url(self, user):
        return f"/api/users/{user.id}/set-store/"

    def test_owner_assigns_changes_and_clears_a_store_location(self):
        response = self.owner.post(self.url(self.pending_user), {"stock_point": self.np.id}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["stock_point"], response.json()["stock_point_name"]), (self.np.id, "Nehru Place"))
        # a real (JWT) request re-reads the user; force_authenticate needs a fresh copy
        reloaded = client_for(User.objects.get(pk=self.pending_user.pk))
        self.assertEqual([i["code"] for i in results(reloaded.get("/api/invoices/"))], ["INV-NP"])
        self.assertEqual(self.owner.post(self.url(self.pending_user), {"stock_point": None}, format="json").status_code, 200)
        self.pending_user.refresh_from_db()
        self.assertIsNone(self.pending_user.stock_point)

    def test_online_channels_and_unknown_ids_are_refused(self):
        self.assertEqual(self.owner.post(self.url(self.pending_user), {"stock_point": self.web.id}, format="json").status_code, 400)
        self.assertEqual(self.owner.post(self.url(self.pending_user), {"stock_point": 999999}, format="json").status_code, 400)
        self.assertEqual(self.owner.post(self.url(self.pending_user), {}, format="json").status_code, 400)
        self.pending_user.refresh_from_db()
        self.assertIsNone(self.pending_user.stock_point)

    def test_staff_cannot_change_their_own_store(self):
        self.assertEqual(self.kb_staff.post(self.url(self.kb_user), {"stock_point": self.np.id}, format="json").status_code, 403)
        # nor through the staff-edit endpoint, which needs roles.manage
        self.assertEqual(self.kb_staff.patch(f"/api/users/{self.kb_user.id}/", {"stock_point": self.np.id}, format="json").status_code, 403)
        self.kb_user.refresh_from_db()
        self.assertEqual(self.kb_user.stock_point, self.kb)

    def test_roles_manage_holders_cannot_assign_stores(self):
        manager = client_for(make_user("kb-manager", ["roles.manage"], stock_point=self.kb))
        colleague = make_user("kb-colleague", stock_point=self.kb)
        self.assertEqual(manager.post(self.url(colleague), {"stock_point": self.np.id}, format="json").status_code, 403)
        colleague.refresh_from_db()
        self.assertEqual(colleague.stock_point, self.kb)

    def test_new_and_existing_staff_start_unassigned_even_with_online_channels_present(self):
        self.assertFalse(User.objects.filter(stock_point__kind=StockPoint.ONLINE).exists())
        fresh = User.objects.create_user(username="fresh", password="safe-test-password")
        self.assertIsNone(fresh.stock_point)

    def test_directory_and_me_expose_assignment_only_within_scope(self):
        me = self.kb_staff.get("/api/users/me/").json()
        self.assertEqual((me["stock_point"], me["sees_all_stores"]), (self.kb.id, False))
        np_user = make_user("np-staff", stock_point=self.np)
        visible = {u["username"] for u in results(self.kb_staff.get("/api/users/"))}
        self.assertIn("kb-staff", visible)
        self.assertNotIn(np_user.username, visible)
        self.assertNotIn("pending", visible)
        self.assertEqual({u["username"] for u in results(self.pending.get("/api/users/"))}, {"pending"})
        self.assertIn(np_user.username, {u["username"] for u in results(self.owner.get("/api/users/"))})

    def test_locator_lists_staff_assigned_to_the_store(self):
        staff = self.owner.get(f"/api/stock-points/{self.kb.id}/locator/").json()["staff"]
        self.assertEqual([(s["username"], s["is_active"]) for s in staff], [("kb-staff", True)])
        self.assertNotIn("phone", staff[0])


class StoreManagementDashboardTests(StoreScopeFixture):
    """The Store & Channel Management dashboard's data: summary cards, inventory views."""

    def setUp(self):
        super().setUp()
        product = Product.objects.create(brand="HP", model_name="EliteBook", product_code="VC-LAP-0002")
        # stocked at Nehru Place only -- Karol Bagh has NO record for it
        self.np_only = Variant.objects.create(product=product, code="VC-SKU-0002", spec="i7", mrp=1, sell_price=1, cost=1)
        Stock.objects.create(variant=self.np_only, stock_point=self.np, quantity=1)
        # a verified zero at Karol Bagh
        self.kb_zero = Variant.objects.create(product=product, code="VC-SKU-0003", spec="i3", mrp=1, sell_price=1, cost=1)
        Stock.objects.create(variant=self.kb_zero, stock_point=self.kb, quantity=0)

    def inventory(self, client):
        response = client.get("/api/stock-points/inventory/")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_summary_counts_zero_and_low_stock_records_per_store(self):
        rows = {r["id"]: r for r in self.owner.get("/api/stock-points/summary/").json()}
        self.assertEqual((rows[self.kb.id]["out_of_stock"], rows[self.kb.id]["low_stock"]), (1, 1))  # 0 units; 3 units
        self.assertEqual((rows[self.np.id]["out_of_stock"], rows[self.np.id]["low_stock"]), (0, 1))  # 9 units; 1 unit

    def test_owner_sees_product_distribution_across_every_store(self):
        data = self.inventory(self.owner)
        self.assertEqual(data["low_stock_threshold"], 4)
        self.assertEqual(len(data["stock_points"]), 3)
        by_code = {v["variant_code"]: {s["stock_point_id"]: s["quantity"] for s in v["stock"]} for v in data["variants"]}
        self.assertEqual(by_code["VC-SKU-0001"], {self.kb.id: 3, self.np.id: 9})
        self.assertEqual(by_code["VC-SKU-0002"], {self.np.id: 1})  # no record at KB -> absent, not 0
        self.assertEqual(by_code["VC-SKU-0003"], {self.kb.id: 0})  # verified zero
        self.assertNotIn("cost", data["variants"][0])
        parts = {p["name"]: {s["stock_point_id"]: s["quantity"] for s in p["stock"]} for p in data["parts"]}
        self.assertEqual(parts["Keyboard"], {self.kb.id: 2, self.np.id: 7})

    def test_store_staff_inventory_holds_only_their_store(self):
        data = self.inventory(self.kb_staff)
        self.assertEqual([sp["id"] for sp in data["stock_points"]], [self.kb.id])
        points = {s["stock_point_id"] for v in data["variants"] for s in v["stock"]}
        points |= {s["stock_point_id"] for p in data["parts"] for s in p["stock"]}
        self.assertEqual(points, {self.kb.id})
        np_only = next(v for v in data["variants"] if v["variant_code"] == "VC-SKU-0002")
        self.assertEqual(np_only["stock"], [])  # catalogue item, but no Nehru Place quantity leaks

    def test_unassigned_staff_get_an_empty_inventory(self):
        data = self.inventory(self.pending)
        self.assertEqual((data["stock_points"], data["variants"], data["parts"]), ([], [], []))

    def test_roles_card_counts_role_records_not_permissions(self):
        from accounts.models import Permission, Role
        roles = results(self.kb_staff.get("/api/roles/"))
        self.assertEqual(len(roles), Role.objects.count())
        self.assertNotEqual(len(roles), Permission.objects.count())

    def test_staff_card_lists_assignments_within_scope(self):
        owner_view = {u["username"]: u["stock_point_name"] for u in results(self.owner.get("/api/users/"))}
        self.assertEqual((owner_view["kb-staff"], owner_view["pending"]), ("Karol Bagh", None))
        staff_view = {u["username"] for u in results(self.kb_staff.get("/api/users/"))}
        self.assertEqual(staff_view, {"kb-staff"})

    def test_active_status_defaults_on_and_is_hidden_from_store_staff(self):
        # Active / Inactive (catalog.status): every stock point starts active, and
        # only administrators see the status -- plain store staff get no field.
        self.assertTrue(StockPoint.objects.get(pk=self.kb.pk).is_active)
        self.assertNotIn("is_active", results(self.kb_staff.get("/api/stock-points/"))[0])
