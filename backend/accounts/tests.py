from django.test import TestCase

from accounts.models import NotificationRule, PermissionDeniedLog, Role, StaffNotification
from crmbook_backend.notify import notify_staff
from crmbook_backend.testing import client_for, make_user, results


class RoleAndUserTests(TestCase):
    def setUp(self):
        self.admin_user = make_user("role-admin", ["roles.manage"])
        self.admin = client_for(self.admin_user)
        self.staff_user = make_user("plain-staff")
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
