from datetime import date, timedelta

from django.apps import apps as django_apps
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import ActivityLog, PermissionDeniedLog, User
from catalog.models import Product, Service, Stock, StockPoint, Variant
from crmbook_backend.testing import assign_store, client_for, make_user, results, give_out
from parties.models import Party
from repairs.models import RepairTicket, RepairTicketEvent

SELL = ["invoices.view", "invoices.create", "invoices.settle", "parties.view", "parties.manage", "parties.edit",
        "inventory.edit", "repairs.view"]
ADMIN = ["roles.manage", *SELL, "repairs.manage", "repairs.book", "rentals.view"]


class ActivityLogTests(TestCase):
    """
    Staff Activity Logs: completed work is recorded server-side, and the
    log API enforces the three tiers (Superuser / Admin / Staff) and store
    isolation before any count, filter, search or page.
    """

    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Customer", type=Party.RETAIL, phone="9876500000", joined=date.today())
        product = Product.objects.create(brand="Dell", model_name="Latitude", product_code="VC-LAP-0001")
        self.variant = Variant.objects.create(product=product, code="VC-SKU-0001", spec="i5", mrp=50000, sell_price=40000, cost=1)
        Stock.objects.create(variant=self.variant, stock_point=self.kb, quantity=50)
        Stock.objects.create(variant=self.variant, stock_point=self.np, quantity=50)
        self.service = Service.objects.create(slug="screen", label="Screen", segment=Service.HARDWARE, charge=6000)

        self.root_user = make_user("root", superuser=True)
        self.root2_user = make_user("root2", superuser=True)
        self.owner_user = make_user("owner", ADMIN, owner=True)
        self.kb_admin_user = make_user("kb-admin", ADMIN, stock_point=self.kb)
        self.kb_admin2_user = make_user("kb-admin2", ADMIN, stock_point=self.kb)
        self.seller_user = make_user("seller", SELL, stock_point=self.kb)
        self.seller2_user = make_user("seller2", SELL, stock_point=self.kb)
        self.np_seller_user = make_user("np-seller", SELL, stock_point=self.np)
        self.loose_user = make_user("unassigned", SELL)
        self.root, self.root2, self.owner = client_for(self.root_user), client_for(self.root2_user), client_for(self.owner_user)
        self.kb_admin, self.kb_admin2 = client_for(self.kb_admin_user), client_for(self.kb_admin2_user)
        self.seller, self.seller2 = client_for(self.seller_user), client_for(self.seller2_user)
        self.np_seller, self.loose = client_for(self.np_seller_user), client_for(self.loose_user)

    # -- helpers --------------------------------------------------------
    def sell(self, client, sp, qty=1):
        return client.post("/api/invoices/", {
            "party": self.party.id, "stock_point": sp.id, "date": date.today().isoformat(),
            "items": [{"variant": self.variant.id, "qty": qty, "price": 40000}],
        }, format="json")

    def logs(self, client, user, **params):
        return client.get(f"/api/users/{user.id}/activity/", params)

    def data(self, client, user, **params):
        response = self.logs(client, user, **params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def entries(self, client, user, **params):
        return self.data(client, user, **params)["results"]

    def log(self, actor, at=None, store=None, actor_store=None, **extra):
        defaults = {"module": "inventory", "action": "updated", "description": "Updated product P-1"}
        defaults.update(extra)
        return ActivityLog.objects.create(actor=actor, at=at or timezone.now(), stock_point=store,
                                          actor_stock_point=actor_store, **defaults)

    # -- recording -----------------------------------------------------
    def test_sale_and_settlement_are_recorded_with_actor_and_store(self):
        invoice = self.sell(self.seller, self.kb).json()
        self.seller.post(f"/api/invoices/{invoice['id']}/settle/", {"pay_method": "Cash"}, format="json")
        rows = ActivityLog.objects.filter(actor=self.seller_user, record_type="sales.invoice").order_by("at", "id")
        self.assertEqual([r.action for r in rows], ["created", "settle"])
        self.assertEqual(rows[0].description, f"Created invoice {invoice['code']}")
        self.assertEqual(rows[1].description, f"Settled invoice {invoice['code']}")
        self.assertEqual({(r.stock_point_id, r.actor_stock_point_id) for r in rows}, {(self.kb.id, self.kb.id)})
        self.assertEqual(rows[1].changes["status"][1], "Paid")
        # the posting the settlement made is its own entry, at the same store
        self.assertTrue(ActivityLog.objects.filter(actor=self.seller_user, module="accounting", stock_point=self.kb).exists())

    def test_store_less_record_keeps_no_store_but_remembers_where_the_actor_worked(self):
        self.seller.patch(f"/api/parties/{self.party.id}/", {"city": "Delhi"}, format="json")
        row = ActivityLog.objects.get(actor=self.seller_user, record_type="parties.party")
        self.assertEqual((row.stock_point_id, row.actor_stock_point_id), (None, self.kb.id))
        entry = self.entries(self.root, self.seller_user, module="parties")[0]
        self.assertIsNone(entry["store"])
        self.assertEqual((entry["record_kind"], entry["record_label"]), ("Customer", "Customer"))

    def test_one_request_one_row_per_record(self):
        response = self.owner.post("/api/tickets/", {
            "party": self.party.id, "brand": "HP", "model_name": "Pavilion", "serial": "SN-1", "stock_point": self.kb.id,
            "issue": "No boot", "service_ids": [self.service.id], "received": date.today().isoformat(), "payment": "full",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        rows = ActivityLog.objects.filter(actor=self.owner_user, record_type="repairs.repairticket")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows[0].description, f"Created repair ticket {response.json()['code']}")
        give_out(RepairTicket.objects.get(pk=response.json()["id"]), self.owner_user)
        stage = self.owner.post(f"/api/tickets/{response.json()['id']}/set-stage/", {"status": RepairTicket.DIAGNOSING}, format="json")
        self.assertEqual(stage.status_code, 200, stage.content)
        self.assertEqual(rows.count(), 2)
        row = rows.order_by("-at", "-id").first()
        self.assertEqual(row.changes["status"], ["Received", "Diagnosing"])

    def test_failed_and_read_requests_record_nothing(self):
        before = ActivityLog.objects.count()
        self.assertEqual(self.sell(self.seller, self.kb, qty=999).status_code, 400)
        self.seller.get("/api/invoices/")
        self.assertEqual(ActivityLog.objects.count(), before)

    def test_add_stock_describes_the_movement(self):
        self.seller.post("/api/inventory/add-stock/", {"stock_point": self.kb.id, "product": self.variant.product_id,
                                                        "variant": self.variant.id, "quantity": 3}, format="json")
        row = ActivityLog.objects.get(actor=self.seller_user, record_type="catalog.stock")
        self.assertEqual(row.description, "Added 3 × Dell Latitude (i5) to stock at Karol Bagh")
        self.assertEqual((row.changes["quantity"], row.stock_point_id), ([50, 53], self.kb.id))

    def test_secrets_are_never_stored_and_personal_fields_are_masked(self):
        self.owner.patch(f"/api/parties/{self.party.id}/", {"phone": "9000000001", "city": "Noida"}, format="json")
        row = ActivityLog.objects.get(actor=self.owner_user, record_type="parties.party")
        self.assertEqual(row.changes["phone"], ["(changed)", "(changed)"])
        self.assertNotIn("9000000001", str(row.changes) + row.description)
        reset = self.owner.post(f"/api/users/{self.seller_user.id}/reset-password/", {"delivery": "link"}, format="json")
        token = reset.json()["setup_url"].rstrip("/").rsplit("/", 1)[-1]
        self.kb_admin.post("/api/users/me/change-password/", {
            "current_password": "safe-test-password", "new_password": "an0ther-Secret!-77", "confirm_password": "an0ther-Secret!-77",
        }, format="json")
        dump = str(list(ActivityLog.objects.values_list("description", "changes", "endpoint")))
        for secret in (token, "an0ther-Secret!-77", "safe-test-password", "pbkdf2"):
            self.assertNotIn(secret, dump)

    def test_permission_denials_stay_in_the_security_log_not_the_timeline(self):
        self.assertEqual(self.seller.post("/api/tickets/", {}, format="json").status_code, 403)
        self.assertTrue(PermissionDeniedLog.objects.filter(user=self.seller_user).exists())
        self.assertFalse(ActivityLog.objects.filter(actor=self.seller_user).exists())
        # an older denial row (copied by migration 0008) is kept but never shown or counted
        self.log(self.seller_user, store=self.kb, module="repairs", action="denied", outcome="denied", description="Blocked: POST /api/tickets/")
        data = self.data(self.seller, self.seller_user)
        self.assertEqual((data["count"], data["summary"]["total"]), (0, 0))
        self.assertTrue(ActivityLog.objects.filter(actor=self.seller_user, outcome="denied").exists())

    # -- Superuser ---------------------------------------------------------
    def test_superuser_reads_admins_staff_and_own(self):
        self.sell(self.seller, self.kb)
        self.sell(self.kb_admin, self.kb)
        self.sell(self.root, self.kb)
        for target in (self.seller_user, self.kb_admin_user, self.owner_user, self.root_user):
            self.assertEqual(self.logs(self.root, target).status_code, 200)
        self.assertEqual(len(self.entries(self.root, self.root_user, module="sales")), 1)

    def test_superuser_peer_logs_hidden_by_default(self):
        self.sell(self.root2, self.kb)
        self.assertEqual(self.logs(self.root, self.root2_user).status_code, 404)
        with override_settings(ACTIVITY_LOGS_SUPERUSER_PEERS=True):
            self.assertEqual(len(self.entries(self.root, self.root2_user, module="sales")), 1)

    # -- Admin -----------------------------------------------------------
    def test_admin_reads_own_and_ordinary_staff_only(self):
        self.sell(self.seller, self.kb)
        self.assertEqual(len(self.entries(self.kb_admin, self.seller_user, module="sales")), 1)
        self.assertEqual(self.logs(self.kb_admin, self.kb_admin_user).status_code, 200)
        # never another Admin -- not even one at the same store, nor the Owner
        self.assertEqual(self.logs(self.kb_admin, self.kb_admin2_user).status_code, 404)
        self.assertEqual(self.logs(self.kb_admin, self.owner_user).status_code, 404)
        self.assertEqual(self.logs(self.owner, self.kb_admin_user).status_code, 404)
        # outside the admin's store: 404 too; the Owner reaches both stores' staff
        self.assertEqual(self.logs(self.kb_admin, self.np_seller_user).status_code, 404)
        self.assertEqual(self.logs(self.owner, self.np_seller_user).status_code, 200)
        rows = {u["id"]: u for u in results(self.kb_admin.get("/api/users/"))}
        self.assertTrue(rows[self.seller_user.id]["can_view_activity"])
        self.assertTrue(rows[self.kb_admin_user.id]["can_view_activity"])
        self.assertFalse(rows[self.kb_admin2_user.id]["can_view_activity"])

    def test_admin_never_sees_superuser_activity(self):
        self.sell(self.root, self.kb)
        root_id = self.root_user.id
        for client in (self.kb_admin, self.owner):
            response = client.get(f"/api/users/{root_id}/activity/")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), client.get("/api/users/999999/activity/").json())
            for params in ({"module": "sales"}, {"page": 2}, {"q": "invoice"}, {"store": self.kb.id}, {"period": "today"}):
                self.assertEqual(client.get(f"/api/users/{root_id}/activity/", params).status_code, 404)
            rows = {u["id"]: u for u in results(client.get("/api/users/"))}
            if root_id in rows:
                self.assertFalse(rows[root_id]["can_view_activity"])

    def test_entries_made_as_superuser_stay_hidden_after_demotion(self):
        assign_store(self.kb, self.root_user)
        self.sell(self.root, self.kb)
        User.objects.filter(pk=self.root_user.pk).update(is_superuser=False)
        demoted = User.objects.get(pk=self.root_user.pk)
        data = self.data(self.kb_admin, demoted)
        self.assertEqual((data["count"], data["summary"]["total"], data["summary"]["by_module"]), (0, 0, []))

    # -- ordinary Staff ------------------------------------------------------
    def test_staff_read_only_their_own_work(self):
        self.sell(self.seller, self.kb)
        self.sell(self.seller2, self.kb)
        mine = self.data(self.seller, self.seller_user)
        self.assertEqual(mine["count"], 1)
        self.assertTrue(mine["staff"]["is_self"])
        me = self.seller.get("/api/users/me/").json()
        self.assertEqual((me["can_view_staff_logs"], me["can_view_own_activity"]), (False, True))
        # nobody else -- same store, another store, admins, superusers, unknown ids: 403, no data
        for target in (self.seller2_user, self.np_seller_user, self.kb_admin_user, self.root_user):
            for params in ({}, {"store": self.kb.id}, {"period": "today"}, {"page": 2}):
                response = self.logs(self.seller, target, **params)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("results", response.json())
        self.assertEqual(self.seller.get("/api/users/999999/activity/").status_code, 403)
        rows = {u["id"]: u["can_view_activity"] for u in results(self.seller.get("/api/users/"))}
        self.assertEqual({k for k, v in rows.items() if v}, {self.seller_user.id})
        self.assertEqual(self.client.get(f"/api/users/{self.seller_user.id}/activity/").status_code, 401)

    def test_staff_see_only_their_store_and_store_params_cannot_widen_it(self):
        self.sell(self.seller, self.kb)
        self.log(self.seller_user, store=self.np, module="sales", action="created", description="Created invoice INV-NP")
        # store-less work done elsewhere / of unknown origin stays out too
        self.log(self.seller_user, actor_store=self.np, description="Updated product P-NP")
        self.log(self.seller_user, description="Updated product P-UNKNOWN")
        self.log(self.seller_user, actor_store=self.kb, description="Updated product P-KB")
        descriptions = {e["description"] for e in self.entries(self.seller, self.seller_user)}
        self.assertNotIn("Created invoice INV-NP", descriptions)
        self.assertNotIn("Updated product P-NP", descriptions)
        self.assertNotIn("Updated product P-UNKNOWN", descriptions)
        self.assertIn("Updated product P-KB", descriptions)
        self.assertEqual(self.entries(self.seller, self.seller_user, store=self.np.id), [])

    def test_store_reassignment_does_not_carry_history_across(self):
        self.sell(self.seller, self.kb)
        assign_store(self.np, self.seller_user)
        self.assertEqual(self.data(self.seller, self.seller_user)["count"], 0)
        # and the admin of the new store doesn't get the old store's work either
        np_admin = client_for(make_user("np-admin", ADMIN, stock_point=self.np))
        self.assertEqual(self.data(np_admin, self.seller_user)["count"], 0)
        self.assertEqual(self.data(self.owner, self.seller_user)["count"], 1)

    def test_unassigned_staff_get_an_empty_timeline(self):
        self.log(self.loose_user, store=self.kb, module="sales", action="created", description="Created invoice INV-X")
        data = self.data(self.loose, self.loose_user)
        self.assertEqual((data["count"], data["results"], data["summary"]["total"]), (0, [], 0))

    # -- periods, numbering, filters -------------------------------------------
    def test_periods_use_whole_days_in_the_configured_timezone(self):
        now = timezone.now()
        self.log(self.seller_user, at=now, actor_store=self.kb, description="Today's work")
        self.log(self.seller_user, at=now - timedelta(days=1), actor_store=self.kb, description="Yesterday's work")
        self.log(self.seller_user, at=now - timedelta(days=40), actor_store=self.kb, description="Old work")
        today = timezone.localdate()
        data = self.data(self.seller, self.seller_user, period="today")
        self.assertEqual([e["description"] for e in data["results"]], ["Today's work"])
        self.assertEqual((data["range"]["period"], data["range"]["from"], data["range"]["to"]), ("today", str(today), str(today)))
        self.assertEqual([e["description"] for e in self.entries(self.seller, self.seller_user, period="yesterday")], ["Yesterday's work"])
        self.assertEqual(len(self.entries(self.seller, self.seller_user, period="month")), 2 if today.day > 1 else 1)
        day = (today - timedelta(days=1)).isoformat()
        self.assertEqual(len(self.entries(self.seller, self.seller_user, date_from=day, date_to=day)), 1)
        self.assertEqual(self.logs(self.seller, self.seller_user, date_from="29/10/2026").status_code, 400)
        self.assertEqual(self.logs(self.seller, self.seller_user, date_from=str(today), date_to=day).status_code, 400)
        empty = self.data(self.seller, self.seller_user, date_from="2001-01-01", date_to="2001-01-01")
        self.assertEqual((empty["count"], empty["results"], empty["summary"]["total"]), (0, [], 3))

    def test_numbering_is_stable_oldest_first_across_pages_and_filters(self):
        start = timezone.now() - timedelta(hours=80)
        for i in range(60):
            self.log(self.seller_user, at=start + timedelta(hours=i), actor_store=self.kb,
                     module="sales" if i % 3 == 0 else "inventory", description=f"Work {i + 1}")
        page1 = self.data(self.seller, self.seller_user)
        self.assertEqual((page1["count"], len(page1["results"])), (60, 50))
        self.assertEqual([e["seq"] for e in page1["results"][:3]], [1, 2, 3])
        self.assertEqual(page1["results"][0]["description"], "Work 1")
        page2 = self.data(self.seller, self.seller_user, page=2)
        self.assertEqual([e["seq"] for e in page2["results"]], list(range(51, 61)))
        # filtered: the same entries keep their timeline numbers (gaps show other work exists)
        sales = self.entries(self.seller, self.seller_user, module="sales")
        self.assertEqual([e["seq"] for e in sales[:3]], [1, 4, 7])
        self.assertEqual([e["seq"] for e in self.entries(self.seller, self.seller_user, q="Work 60")], [60])

    def test_identity_summary_and_search(self):
        invoice = self.sell(self.seller, self.kb).json()
        self.seller.patch(f"/api/parties/{self.party.id}/", {"city": "Delhi"}, format="json")
        data = self.data(self.kb_admin, self.seller_user)
        self.assertEqual((data["staff"]["username"], data["staff"]["store"]["name"], data["timezone"]), ("seller", "Karol Bagh", "UTC"))
        self.assertEqual(data["summary"]["total"], data["count"])
        self.assertEqual({m["module"] for m in data["summary"]["by_module"]}, {"sales", "parties"})
        self.assertEqual(len(self.entries(self.kb_admin, self.seller_user, q=invoice["code"])), 1)
        self.assertEqual({e["action"] for e in self.entries(self.kb_admin, self.seller_user, kind="created")}, {"created"})
        self.assertEqual(len(self.entries(self.kb_admin, self.seller_user, store="none")), 1)

    def test_module_permissions_still_apply(self):
        self.sell(self.seller, self.kb)
        thin = client_for(make_user("thin-admin", ["roles.manage"], stock_point=self.kb))
        data = self.data(thin, self.seller_user)
        self.assertFalse(any(e["module"] == "sales" for e in data["results"]))
        self.assertNotIn("sales", [m["id"] for m in data["modules"]])

    def test_earlier_repair_history_is_imported_as_such(self):
        import importlib
        migration = importlib.import_module("accounts.migrations.0008_import_earlier_activity")
        ticket = RepairTicket.objects.create(code="RPR-OLD", party=self.party, brand="HP", model_name="X",
                                             stock_point=self.kb, issue="x", received=date.today())
        RepairTicketEvent.objects.create(ticket=ticket, event_type=RepairTicketEvent.STAGE_CHANGED, actor=self.seller_user)
        RepairTicketEvent.objects.create(ticket=ticket, event_type=RepairTicketEvent.APPROVAL_DECIDED, actor=None)
        migration.import_earlier(django_apps, None)
        rows = ActivityLog.objects.filter(source="imported", actor=self.seller_user)
        self.assertEqual([(r.description, r.stock_point_id) for r in rows], [("Stage changed - repair ticket RPR-OLD", self.kb.id)])
        entry = self.entries(self.kb_admin, self.seller_user, module="repairs")[0]
        self.assertEqual(entry["source"], "imported")


class ActivityLogSchemaAndPeriodTests(TestCase):
    """
    Guards for the failure seen when the model gained actor_stock_point
    before its migration was applied: the model's columns must exist in the
    real table, no model change may lack a migration, and every period must
    run the row query (not just COUNT) when entries match.
    """

    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.root_user = make_user("root", superuser=True)
        self.admin_user = make_user("kb-admin", ADMIN, stock_point=self.kb)
        self.staff_user = make_user("staff", SELL, stock_point=self.kb)
        self.other_user = make_user("other", SELL, stock_point=self.kb)
        self.root, self.admin = client_for(self.root_user), client_for(self.admin_user)
        self.staff, self.other = client_for(self.staff_user), client_for(self.other_user)

    def test_model_columns_match_the_database_table(self):
        from django.core.management import call_command
        from django.db import connection

        with connection.cursor() as cursor:
            columns = {c.name for c in connection.introspection.get_table_description(cursor, ActivityLog._meta.db_table)}
        self.assertEqual({f.column for f in ActivityLog._meta.concrete_fields}, columns)
        # no model change waiting for a migration (raises SystemExit if one is missing)
        call_command("makemigrations", "accounts", check=True, dry_run=True, verbosity=0)

    def _entries_around(self, user, moments):
        for label, at in moments.items():
            ActivityLog.objects.create(actor=user, at=at, module="inventory", action="updated",
                                       description=label, actor_stock_point=self.kb)

    def _periods(self, client, user, today):
        from unittest import mock
        out = {}
        with mock.patch("django.utils.timezone.localdate", return_value=today):
            for period in ("today", "yesterday", "week", "month"):
                response = client.get(f"/api/users/{user.id}/activity/", {"period": period})
                self.assertEqual(response.status_code, 200, response.content)
                out[period] = sorted(e["description"] for e in response.json()["results"])
        return out

    def test_period_boundaries_are_whole_days(self):
        from datetime import datetime, timezone as dt_tz

        # Thursday 2026-10-29 (week from Mon 26 Oct, month from 1 Oct), in TIME_ZONE (UTC)
        today = date(2026, 10, 29)
        utc = lambda *a: datetime(*a, tzinfo=dt_tz.utc)
        self._entries_around(self.staff_user, {
            "today-start": utc(2026, 10, 29, 0, 0, 0), "today-end": utc(2026, 10, 29, 23, 59, 59),
            "yesterday": utc(2026, 10, 28, 12, 0), "monday": utc(2026, 10, 26, 0, 0, 1),
            "sunday-before": utc(2026, 10, 25, 23, 59, 59), "first-of-month": utc(2026, 10, 1, 0, 0),
            "last-month": utc(2026, 9, 30, 23, 59, 59), "tomorrow": utc(2026, 10, 30, 0, 0),
        })
        for client in (self.staff, self.admin, self.root):  # own view, admin view, superuser view
            got = self._periods(client, self.staff_user, today)
            self.assertEqual(got["today"], ["today-end", "today-start"])
            self.assertEqual(got["yesterday"], ["yesterday"])
            self.assertEqual(got["week"], ["monday", "today-end", "today-start", "yesterday"])
            self.assertEqual(got["month"], ["first-of-month", "monday", "sunday-before", "today-end", "today-start", "yesterday"])

    def test_every_period_and_page_evaluates_rows_for_several_users(self):
        now = timezone.now()
        for user in (self.staff_user, self.other_user, self.admin_user):
            for i in range(55):
                ActivityLog.objects.create(actor=user, at=now - timedelta(hours=i), module="inventory", action="updated",
                                           description=f"{user.username} work {i}", actor_stock_point=self.kb)
        old_day = (timezone.localdate() - timedelta(days=2)).isoformat()
        cases = [(self.staff, self.staff_user), (self.other, self.other_user), (self.admin, self.admin_user),
                 (self.admin, self.staff_user), (self.root, self.staff_user), (self.root, self.admin_user)]
        for client, target in cases:
            for params in ({}, {"period": "today"}, {"period": "yesterday"}, {"period": "week"}, {"period": "month"},
                           {"date_from": old_day, "date_to": old_day}, {"date_from": "2001-01-01", "date_to": "2001-12-31"}):
                response = client.get(f"/api/users/{target.id}/activity/", params)
                self.assertEqual(response.status_code, 200, (target.username, params, response.content))
                data = response.json()
                self.assertTrue(all(e["description"].startswith(target.username) for e in data["results"]))
                if data["next"]:
                    page2 = client.get(f"/api/users/{target.id}/activity/", {**params, "page": 2})
                    self.assertEqual(page2.status_code, 200)
                    self.assertGreater(page2.json()["results"][0]["seq"], data["results"][-1]["seq"])
            self.assertEqual(client.get(f"/api/users/{target.id}/activity/", {"date_from": "2001-01-01", "date_to": "2001-12-31"}).json()["count"], 0)
        # and the walls still stand: staff can't read each other, admins can't read the superuser
        self.assertEqual(self.staff.get(f"/api/users/{self.other_user.id}/activity/").status_code, 403)
        self.assertEqual(self.admin.get(f"/api/users/{self.root_user.id}/activity/").status_code, 404)
