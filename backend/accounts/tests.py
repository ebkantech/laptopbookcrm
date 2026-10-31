from django.test import Client, TestCase, override_settings

from accounts.models import NotificationRule, PermissionDeniedLog, Role, StaffNotification
from catalog.models import StockPoint
from crmbook_backend.notify import notify_staff
from crmbook_backend.testing import client_for, make_user, results


class RoleAndUserTests(TestCase):
    def setUp(self):
        # both work at the same shop -- a roles.manage holder only manages
        # their own store's team (the user directory is store-scoped)
        shop = StockPoint.objects.create(slug="roles-shop", name="Roles Shop", kind=StockPoint.SHOP)
        self.admin_user = make_user("role-admin", ["roles.manage"], stock_point=shop)
        self.admin = client_for(self.admin_user)
        self.staff_user = make_user("plain-staff", stock_point=shop)
        self.staff = client_for(self.staff_user)

    def test_me_returns_own_permissions(self):
        body = self.admin.get("/api/users/me/").json()
        self.assertEqual((body["username"], body["permissions"]), ("role-admin", ["roles.manage"]))

    def test_any_staff_can_list_roles_but_only_roles_manage_can_create(self):
        self.assertEqual(self.staff.get("/api/roles/").status_code, 200)
        self.assertEqual(self.staff.post("/api/roles/", {"slug": "x", "label": "X"}, format="json").status_code, 403)

        response = self.admin.post("/api/roles/", {
            "slug": "store_lead", "label": "Store lead", "permission_codes": ["roles.manage"],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(Role.objects.get(slug="store_lead").has_perm("roles.manage"))

    def test_role_validation(self):
        owner_slug = self.admin.post("/api/roles/", {"slug": "owner", "label": "Fake owner"}, format="json")
        self.assertEqual(owner_slug.status_code, 400)
        unknown = self.admin.post("/api/roles/", {"slug": "r", "label": "R", "permission_codes": ["no.such"]}, format="json")
        self.assertEqual(unknown.status_code, 400)

    def test_cannot_delete_role_still_in_use(self):
        role = self.staff_user.role
        self.assertEqual(self.admin.delete(f"/api/roles/{role.id}/").status_code, 400)
        self.staff_user.role = None
        self.staff_user.save()
        self.assertEqual(self.admin.delete(f"/api/roles/{role.id}/").status_code, 204)

    def test_set_role(self):
        target = Role.objects.create(slug="cashier", label="Cashier")
        url = f"/api/users/{self.staff_user.id}/set-role/"
        self.assertEqual(self.staff.post(url, {"role": "cashier"}, format="json").status_code, 403)
        self.assertEqual(self.admin.post(url, {"role": "owner"}, format="json").status_code, 400)
        self.assertEqual(self.admin.post(url, {"role": "missing"}, format="json").status_code, 400)
        self.assertEqual(self.admin.post(url, {"role": "cashier"}, format="json").status_code, 200)
        self.staff_user.refresh_from_db()
        self.assertEqual(self.staff_user.role, target)

    def test_permission_denial_is_logged(self):
        self.staff.get("/api/notification-rules/")
        log = PermissionDeniedLog.objects.get(user=self.staff_user)
        self.assertEqual((log.required_perm, log.method), ("roles.manage", "GET"))

    @override_settings(CSRF_TRUSTED_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173"])
    def test_session_api_bootstraps_and_enforces_csrf_for_vite_origin(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin_user)
        csrf = client.get("/api/auth/csrf/")
        self.assertEqual(csrf.status_code, 200)
        token = csrf.cookies["csrftoken"].value
        self.assertEqual(client.post("/api/auth/csrf/", HTTP_X_CSRFTOKEN=token).status_code, 405)

        payload = {"slug": "csrf-role", "label": "CSRF role", "permission_codes": ["roles.manage"]}
        blocked = client.post("/api/roles/", payload, content_type="application/json", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(blocked.status_code, 403)
        accepted = client.post("/api/roles/", payload, content_type="application/json", HTTP_ORIGIN="http://localhost:5173", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(accepted.status_code, 201, accepted.content)


class StaffNotificationTests(TestCase):
    def setUp(self):
        self.user = make_user("bell-user")
        self.other = make_user("other-user")
        NotificationRule.objects.create(
            event_key="payment_received", role=self.user.role, via_email=False, via_whatsapp=False, via_inapp=True,
        )
        self.client_ = client_for(self.user)

    def test_notify_staff_writes_inbox_only_for_roles_with_a_rule(self):
        notify_staff("payment_received", "Invoice INV-1 settled", "Paid in full.")
        self.assertEqual(StaffNotification.objects.filter(user=self.user).count(), 1)
        self.assertEqual(StaffNotification.objects.filter(user=self.other).count(), 0)

    def test_inbox_is_scoped_to_the_user_and_can_be_marked_read(self):
        StaffNotification.objects.create(user=self.user, event_key="payment_received", subject="Mine")
        StaffNotification.objects.create(user=self.other, event_key="payment_received", subject="Not mine")

        self.assertEqual([n["subject"] for n in results(self.client_.get("/api/my-notifications/"))], ["Mine"])
        self.assertEqual(self.client_.get("/api/my-notifications/unread_count/").json()["count"], 1)
        self.client_.post("/api/my-notifications/mark_all_read/")
        self.assertEqual(self.client_.get("/api/my-notifications/unread_count/").json()["count"], 0)
        # the other user's notification is untouched
        self.assertIsNone(StaffNotification.objects.get(user=self.other).read_at)


class StaffLoginTests(TestCase):
    """POST /api/auth/token/ works whatever the account's Store Location -- store
    scope limits data, never sign-in."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # the login throttle counts attempts in the cache
        self.shop = StockPoint.objects.create(slug="login-shop", name="Login Shop", kind=StockPoint.SHOP)
        self.owner = make_user("login-owner", superuser=True)
        self.assigned = make_user("login-assigned", ["invoices.view"], stock_point=self.shop)
        self.unassigned = make_user("login-unassigned", ["invoices.view"])

    def login(self, username, password="safe-test-password"):
        return Client().post("/api/auth/token/", {"username": username, "password": password}, content_type="application/json")

    def test_owner_assigned_and_unassigned_staff_can_all_sign_in(self):
        for user in (self.owner, self.assigned, self.unassigned):
            response = self.login(user.username)
            self.assertEqual(response.status_code, 200, (user.username, response.content))
            self.assertIn("access", response.json())

    def test_wrong_password_is_401_not_a_server_error(self):
        self.assertEqual(self.login("login-unassigned", "wrong-password").status_code, 401)
