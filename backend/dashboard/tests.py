from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Permission, Role
from dashboard.layouts import effective_layout
from dashboard.models import DashboardLayout, DashboardLayoutItem, DashboardWidget


class DashboardLayoutTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="dash-owner", password="safe-test-password", is_superuser=True)
        self.repair_role = Role.objects.create(slug="test_repair_only", label="Test repair only")
        self.repair_role.permissions.add(Permission.objects.get_or_create(codename="repairs.view", defaults={"description": "View repairs"})[0])
        self.tech = User.objects.create_user(username="dash-tech", password="safe-test-password", role=self.repair_role)

    def keys(self, user):
        return [w["key"] for w in effective_layout(user)["widgets"]]

    def test_catalog_is_seeded_with_current_dashboard_elements(self):
        self.assertEqual(DashboardWidget.objects.count(), 14)
        self.assertTrue(DashboardWidget.objects.filter(key="chart-monthly-revenue", kind="chart", chart_type="line").exists())

    def test_superuser_gets_every_widget_in_default_order(self):
        layout = effective_layout(self.owner)
        self.assertEqual(layout["source"], "default")
        self.assertEqual(self.keys(self.owner), list(DashboardWidget.objects.values_list("key", flat=True)))

    def test_role_only_sees_widgets_for_its_sections(self):
        sections = {w["section"] for w in effective_layout(self.tech)["widgets"]}
        # repairs.view also unlocks the stock section (parts on the shelf)
        self.assertEqual(sections, {"repairs", "stock"})

    def test_user_layout_beats_role_layout_and_keeps_unplaced_widgets(self):
        stages = DashboardWidget.objects.get(key="panel-repair-stages")
        overdue = DashboardWidget.objects.get(key="kpi-repairs-overdue")
        role_layout = DashboardLayout.objects.create(role=self.repair_role)
        DashboardLayoutItem.objects.create(layout=role_layout, widget=overdue, position=0)
        self.assertEqual(effective_layout(self.tech)["source"], "role")
        self.assertEqual(self.keys(self.tech)[0], "kpi-repairs-overdue")

        mine = DashboardLayout.objects.create(user=self.tech)
        DashboardLayoutItem.objects.create(layout=mine, widget=stages, position=0, width=6, settings={"compact": True})
        DashboardLayoutItem.objects.create(layout=mine, widget=overdue, position=1, is_visible=False)
        layout = effective_layout(self.tech)
        self.assertEqual(layout["source"], "user")
        first, second = layout["widgets"][:2]
        self.assertEqual((first["key"], first["width"], first["settings"]), ("panel-repair-stages", 6, {"compact": True}))
        self.assertFalse(second["visible"])
        # widgets the user never placed still show up, after the saved ones
        self.assertEqual(len(layout["widgets"]), len(self.keys(self.tech)))
        self.assertIn("kpi-stock-on-hand", self.keys(self.tech)[2:])

    def test_saved_layout_cannot_leak_widgets_from_hidden_sections(self):
        mine = DashboardLayout.objects.create(user=self.tech)
        DashboardLayoutItem.objects.create(layout=mine, widget=DashboardWidget.objects.get(key="kpi-sales-revenue"))
        self.assertNotIn("kpi-sales-revenue", self.keys(self.tech))

    def test_layout_must_have_exactly_one_owner(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DashboardLayout.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DashboardLayout.objects.create(role=self.repair_role, user=self.tech)

    def test_layout_endpoint(self):
        client = APIClient()
        client.force_authenticate(self.tech)
        response = client.get("/api/dashboard/layout/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["grid_columns"], 12)
        summary = client.get("/api/dashboard/summary/").json()
        self.assertEqual(summary["sections"], {"stock": True, "sales": False, "repairs": True, "rentals": False})
