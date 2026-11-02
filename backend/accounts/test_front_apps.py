from django.test import TestCase

from crmbook_backend.testing import client_for, make_user
from catalog.models import StockPoint


class DashboardLocatorReportsGates(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="s", name="S", kind=StockPoint.SHOP)
        self.worker = make_user("w", ("repairs.view", "repairs.manage"), stock_point=self.shop)
        self.office = make_user("o", ("dashboard.view", "storelocator.view", "invoices.view"), stock_point=self.shop)

    def test_repair_staff_cannot_open_dashboard_or_locator(self):
        c = client_for(self.worker)
        self.assertEqual(c.get("/api/dashboard/summary/").status_code, 403)
        self.assertEqual(c.get("/api/dashboard/layout/").status_code, 403)
        self.assertEqual(c.get("/api/stock-points/summary/").status_code, 403)
        self.assertEqual(c.get("/api/stock-points/inventory/").status_code, 403)
        # the plain store list stays open -- forms (new ticket, assign) need it
        self.assertEqual(c.get("/api/stock-points/").status_code, 200)

    def test_granted_role_can(self):
        c = client_for(self.office)
        self.assertEqual(c.get("/api/dashboard/summary/").status_code, 200)
        self.assertEqual(c.get("/api/stock-points/summary/").status_code, 200)
        self.assertEqual(c.get("/api/stock-points/inventory/").status_code, 200)
