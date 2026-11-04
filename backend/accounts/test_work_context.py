"""
Store switcher + role switcher (accounts.context): the X-Active-Store /
X-Active-Role headers, validated against the account's own assignments on
every request. These tests sign in with real JWTs -- force_authenticate
would skip the authentication step that applies the context.
"""
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Permission, Role, User
from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Party
from sales.models import Invoice


def role(slug, perms):
    r = Role.objects.create(slug=slug, label=slug.replace("-", " ").title())
    for code in perms:
        r.permissions.add(Permission.objects.get_or_create(codename=code, defaults={"description": code})[0])
    return r


class WorkContextTests(TestCase):
    def setUp(self):
        self.ln = StockPoint.objects.create(slug="ctx-ln", name="Lajpat Nagar", kind=StockPoint.SHOP)
        self.kb = StockPoint.objects.create(slug="ctx-kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="ctx-np", name="Nehru Place", kind=StockPoint.SHOP)
        self.amazon = StockPoint.objects.create(slug="ctx-amazon", name="Amazon", kind=StockPoint.ONLINE)
        party = Party.objects.create(name="Ctx Buyer", type=Party.RETAIL, phone="9876500111", joined=date.today())
        self.invoices = {
            sp.slug: Invoice.objects.create(code=f"INV-{sp.slug}", party=party, stock_point=sp, date=date.today())
            for sp in (self.ln, self.kb, self.np, self.amazon)
        }
        self.admin_role = role("store-admin", ["roles.manage", "invoices.view", "parties.view"])
        self.rental_role = role("rental-staff", ["rentals.view"])
        self.owner = make_user("ctx-owner", ["invoices.view", "parties.view"], owner=True)
        self.superuser = make_user("ctx-super", superuser=True)
        # Admin + Rental Staff, working at Lajpat Nagar and Karol Bagh
        self.multi = User.objects.create_user("ctx-multi", password="safe-test-password", role=self.admin_role, stock_point=self.ln)
        self.multi.roles.add(self.rental_role)
        self.multi.stock_points.add(self.kb)
        # only Rental Staff, only Lajpat Nagar
        self.renter = User.objects.create_user("ctx-renter", password="safe-test-password", role=self.rental_role, stock_point=self.ln)

    def api(self, user, store=None, role=None):
        client = APIClient()
        headers = {}
        if store is not None:
            headers["HTTP_X_ACTIVE_STORE"] = str(store)
        if role is not None:
            headers["HTTP_X_ACTIVE_ROLE"] = str(role)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}", **headers)
        return client

    def me(self, user, **context):
        response = self.api(user, **context).get("/api/users/me/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def invoice_codes(self, user, **context):
        response = self.api(user, **context).get("/api/invoices/")
        self.assertEqual(response.status_code, 200, response.content)
        return sorted(i["code"] for i in results(response))

    # -- store lists -----------------------------------------------------
    def test_owner_and_superuser_see_every_physical_store_and_all_stores(self):
        for user in (self.owner, self.superuser):
            data = self.me(user)
            self.assertEqual([s["name"] for s in data["accessible_stores"]], ["Karol Bagh", "Lajpat Nagar", "Nehru Place"])
            self.assertTrue(data["can_select_all_stores"])
            self.assertIsNone(data["active_store"])  # All Stores by default

    def test_staff_see_only_their_assigned_stores_and_never_all_stores(self):
        one = self.me(self.renter)
        self.assertEqual([s["name"] for s in one["accessible_stores"]], ["Lajpat Nagar"])
        self.assertFalse(one["can_select_all_stores"])
        two = self.me(self.multi)
        self.assertEqual([s["name"] for s in two["accessible_stores"]], ["Karol Bagh", "Lajpat Nagar"])
        self.assertEqual(two["active_store"], self.ln.id)  # the primary store by default

    def test_online_channels_are_never_listed_as_branches(self):
        names = [s["name"] for s in self.me(self.owner)["accessible_stores"]]
        self.assertNotIn("Amazon", names)

    # -- store validation ------------------------------------------------
    def test_a_store_outside_the_assignment_or_all_stores_for_staff_is_refused(self):
        for value in (self.np.id, self.amazon.id, "all", 999999, "abc"):
            response = self.api(self.multi, store=value).get("/api/invoices/")
            self.assertEqual(response.status_code, 403, value)
            self.assertEqual(response.json()["code"], "invalid_active_store")

    def test_owner_may_pick_any_store_but_not_one_that_does_not_exist(self):
        self.assertEqual(self.api(self.owner, store=self.np.id).get("/api/invoices/").status_code, 200)
        self.assertEqual(self.api(self.owner, store=999999).get("/api/invoices/").status_code, 403)

    # -- every store-scoped module follows the store in view -------------
    def test_invoices_follow_the_store_in_view(self):
        self.assertEqual(self.invoice_codes(self.owner), sorted(i.code for i in self.invoices.values()))
        self.assertEqual(self.invoice_codes(self.owner, store="all"), sorted(i.code for i in self.invoices.values()))
        self.assertEqual(self.invoice_codes(self.owner, store=self.ln.id), ["INV-ctx-ln"])
        self.assertEqual(self.invoice_codes(self.multi), ["INV-ctx-ln"])
        self.assertEqual(self.invoice_codes(self.multi, store=self.kb.id), ["INV-ctx-kb"])

    def test_dashboard_reports_the_store_in_view(self):
        scope = self.api(self.owner, store=self.kb.id).get("/api/dashboard/summary/").json()["store_scope"]
        self.assertEqual((scope["all_stores"], scope["stock_point"]), (False, self.kb.id))
        scope = self.api(self.owner).get("/api/dashboard/summary/").json()["store_scope"]
        self.assertTrue(scope["all_stores"])

    def test_staff_list_follows_the_store_in_view(self):
        kb_staff = make_user("ctx-kb-staff", ["parties.view"], stock_point=self.kb)
        names = lambda **c: {u["username"] for u in results(self.api(self.multi, **c).get("/api/users/"))}  # noqa: E731
        self.assertNotIn(kb_staff.username, names())
        self.assertIn(kb_staff.username, names(store=self.kb.id))

    def test_owner_privileges_do_not_shrink_with_the_store_in_view(self):
        # the store directory and business-wide actions stay the Owner's
        listed = {s["slug"] for s in results(self.api(self.owner, store=self.ln.id).get("/api/stock-points/"))}
        self.assertTrue({"ctx-ln", "ctx-kb", "ctx-np", "ctx-amazon"} <= listed)
        response = self.api(self.owner, store=self.ln.id).patch(f"/api/stock-points/{self.kb.id}/", {"phone": "01140000000"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    # -- roles -----------------------------------------------------------
    def test_only_the_accounts_own_roles_are_offered(self):
        data = self.me(self.multi)
        self.assertEqual(sorted(r["slug"] for r in data["assigned_roles"]), ["rental-staff", "store-admin"])
        self.assertEqual(data["active_role"], self.admin_role.id)
        self.assertEqual([r["slug"] for r in self.me(self.renter)["assigned_roles"]], ["rental-staff"])

    def test_a_role_not_assigned_is_refused(self):
        for value in (self.admin_role.id, Role.objects.get(slug="owner").id, 999999, "store-admin"):
            response = self.api(self.renter, role=value).get("/api/users/me/")
            self.assertEqual(response.status_code, 403, value)
            self.assertEqual(response.json()["code"], "invalid_active_role")

    def test_switching_role_switches_permissions_on_the_server(self):
        as_admin = self.me(self.multi, role=self.admin_role.id)
        as_renter = self.me(self.multi, role=self.rental_role.id)
        self.assertIn("invoices.view", as_admin["permissions"])
        self.assertEqual(as_renter["permissions"], ["rentals.view"])
        self.assertEqual((as_renter["role_label"], as_renter["access_level"]), ("Rental Staff", "staff"))
        # not just hidden menus: the API itself refuses what the active role lacks
        self.assertEqual(self.api(self.multi, role=self.rental_role.id).get("/api/invoices/").status_code, 403)
        self.assertEqual(self.api(self.multi, role=self.admin_role.id).get("/api/invoices/").status_code, 200)

    def test_a_switch_lasts_one_request_and_is_never_saved(self):
        self.api(self.multi, role=self.rental_role.id).post("/api/users/me/change-password/", {}, format="json")
        self.multi.refresh_from_db()
        self.assertEqual(self.multi.role_id, self.admin_role.id)
        self.assertEqual(self.me(self.multi)["active_role"], self.admin_role.id)

        user = User.objects.get(pk=self.multi.pk)
        user._primary_role_id, user.role = user.role_id, self.rental_role
        user.save()  # a full save while switched
        user.refresh_from_db()
        self.assertEqual(user.role_id, self.admin_role.id)

    def test_role_and_store_are_independent(self):
        data = self.me(self.multi, role=self.rental_role.id, store=self.kb.id)
        self.assertEqual((data["active_role"], data["active_store"]), (self.rental_role.id, self.kb.id))
        data = self.me(self.multi, role=self.admin_role.id, store=self.kb.id)
        self.assertEqual((data["active_role"], data["active_store"]), (self.admin_role.id, self.kb.id))
        data = self.me(self.multi, role=self.rental_role.id, store=self.ln.id)
        self.assertEqual((data["active_role"], data["active_store"]), (self.rental_role.id, self.ln.id))

    def test_single_role_single_store_accounts_work_as_before(self):
        data = self.me(self.renter)
        self.assertEqual((data["active_role"], data["active_store"], data["permissions"]), (self.rental_role.id, self.ln.id, ["rentals.view"]))
        self.assertEqual(self.me(self.superuser)["assigned_roles"], [])


class RoleAssignmentTests(TestCase):
    """Assigning several roles / stores (Settings > Staff, PATCH /users/<id>/)."""

    def setUp(self):
        self.ln = StockPoint.objects.create(slug="as-ln", name="Lajpat Nagar", kind=StockPoint.SHOP)
        self.kb = StockPoint.objects.create(slug="as-kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.sales = role("as-sales", ["invoices.view"])
        self.accounts = role("as-accounts", ["cashbook.view"])
        self.owner = client_for(make_user("as-owner", ["roles.manage", "invoices.view", "cashbook.view"], owner=True))
        self.store_admin = client_for(make_user("as-admin", ["roles.manage", "invoices.view"], stock_point=self.ln))
        self.target = User.objects.create_user("as-target", password="safe-test-password", role=self.sales, stock_point=self.ln)

    def test_the_primary_role_and_store_are_always_assigned(self):
        self.assertEqual(set(self.target.roles.all()), {self.sales})
        self.assertEqual(set(self.target.stock_points.all()), {self.ln})

    def test_owner_assigns_extra_roles_and_stores(self):
        response = self.owner.patch(f"/api/users/{self.target.id}/", {"roles": [self.accounts.id], "stock_points": [self.kb.id]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()["roles"]), {self.sales.id, self.accounts.id})  # primary kept
        self.assertEqual(set(response.json()["stock_points"]), {self.ln.id, self.kb.id})

    def test_changing_the_primary_role_takes_the_old_one_away(self):
        self.target.roles.add(self.accounts)
        self.owner.post(f"/api/users/{self.target.id}/set-role/", {"role": "as-accounts"}, format="json")
        self.target.refresh_from_db()
        self.assertEqual(set(self.target.roles.all()), {self.accounts})

    def test_no_privilege_escalation_through_extra_roles_or_stores(self):
        response = self.store_admin.patch(f"/api/users/{self.target.id}/", {"roles": [self.sales.id, self.accounts.id]}, format="json")
        self.assertEqual(response.status_code, 403)  # cashbook.view isn't the admin's to grant
        response = self.store_admin.patch(f"/api/users/{self.target.id}/", {"stock_points": [self.ln.id, self.kb.id]}, format="json")
        self.assertEqual(response.status_code, 403)  # store access is the Owner's call
        owner_role = Role.objects.get(slug="owner")
        response = self.owner.patch(f"/api/users/{self.target.id}/", {"roles": [owner_role.id]}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(set(self.target.roles.all()), {self.sales})

    def test_online_channels_cannot_be_assigned_as_workplaces(self):
        amazon = StockPoint.objects.create(slug="as-amazon", name="Amazon", kind=StockPoint.ONLINE)
        response = self.owner.patch(f"/api/users/{self.target.id}/", {"stock_points": [amazon.id]}, format="json")
        self.assertEqual(response.status_code, 400)


class MultiAssignmentMigrationTests(TransactionTestCase):
    """accounts 0012: existing role / Store Location assignments are copied, nothing else changes."""

    before = [("accounts", "0011_expenses_permission"), ("catalog", "0006_variant_colour")]
    after = [("accounts", "0012_user_roles_stock_points")]

    def test_existing_assignments_are_carried_over(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        shop = old.get_model("catalog", "StockPoint").objects.create(slug="mig-shop", name="Mig Shop", kind="shop")
        sales = old.get_model("accounts", "Role").objects.create(slug="mig-sales", label="Mig Sales")
        OldUser = old.get_model("accounts", "User")
        assigned = OldUser.objects.create(username="mig-assigned", password="hash-kept", role=sales, stock_point=shop)
        bare = OldUser.objects.create(username="mig-bare", password="hash-kept-too")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        User = new.get_model("accounts", "User")
        moved = User.objects.get(pk=assigned.pk)
        self.assertEqual((moved.role_id, moved.stock_point_id, moved.password), (sales.pk, shop.pk, "hash-kept"))
        self.assertEqual(list(moved.roles.values_list("pk", flat=True)), [sales.pk])
        self.assertEqual(list(moved.stock_points.values_list("pk", flat=True)), [shop.pk])
        untouched = User.objects.get(pk=bare.pk)
        self.assertEqual((untouched.roles.count(), untouched.stock_points.count(), untouched.password), (0, 0, "hash-kept-too"))
