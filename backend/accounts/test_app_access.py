from django.test import TestCase

from accounts.app_catalog import app_for, catalog
from accounts.models import Permission, Role
from crmbook_backend.testing import client_for, make_user


class AppAccessTests(TestCase):
    def setUp(self):
        self.sa = make_user("sa", superuser=True)
        self.admin = make_user("adm", ("roles.manage", "repairs.view", "repairs.manage", "rentals.view"))
        for code in ("repairs.view", "repairs.manage", "repairs.approve", "rentals.view", "leads.view", "cashbook.view"):
            Permission.objects.get_or_create(codename=code, defaults={"description": code})
        self.role = Role.objects.create(slug="helper", label="Helper")

    def patch(self, user, codes):
        return client_for(user).patch(f"/api/roles/{self.role.pk}/", {"permission_codes": codes}, format="json")

    def test_catalog_groups_permissions_by_app(self):
        self.assertEqual(app_for("repairs.book"), "repairs")
        self.assertEqual(app_for("payments.send_link"), "invoices")
        self.assertEqual(app_for("weird.thing"), "other")
        keys = {a["key"]: a for a in catalog(["repairs.view", "repairs.manage", "leads.view"])}
        self.assertEqual(keys["repairs"]["permissions"], ["repairs.manage", "repairs.view"])
        self.assertEqual(keys["repairs"]["view"], "repairs.view")
        self.assertNotIn("rentals", keys)

    def test_apps_endpoint_is_readable_by_staff(self):
        r = client_for(self.admin).get("/api/roles/apps/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("repairs", [a["key"] for a in r.data])

    def test_admin_can_grant_only_what_they_hold(self):
        self.assertEqual(self.patch(self.admin, ["repairs.view", "rentals.view"]).status_code, 200)
        self.assertEqual(set(self.role.permissions.values_list("codename", flat=True)), {"repairs.view", "rentals.view"})
        r = self.patch(self.admin, ["repairs.view", "rentals.view", "cashbook.view"])
        self.assertEqual(r.status_code, 403)
        self.assertIn("cashbook.view", r.data["detail"])
        r = client_for(self.admin).post("/api/roles/", {"slug": "x", "label": "X", "permission_codes": ["leads.view"]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_admin_cannot_strip_access_they_lack_either(self):
        self.role.permissions.set(Permission.objects.filter(codename__in=["cashbook.view", "repairs.view"]))
        self.assertEqual(self.patch(self.admin, ["repairs.view"]).status_code, 403)  # would drop cashbook.view

    def test_super_admin_can_grant_anything(self):
        self.assertEqual(self.patch(self.sa, ["cashbook.view", "leads.view"]).status_code, 200)
