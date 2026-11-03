from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Message, Party
from sales.models import Invoice
from sales.services import create_invoice, on_invoice_paid

from .models import Warranty, WarrantyClaim


class Base(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="s1", name="Main Shop", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="s2", name="Other Shop", kind=StockPoint.SHOP)
        self.staff = make_user("wstaff", ("warranty.manage", "invoices.view"), stock_point=self.shop)
        self.viewer = make_user("wview", ("invoices.view",), stock_point=self.shop)
        self.c, self.v = client_for(self.staff), client_for(self.viewer)
        self.party = Party.objects.create(name="Asha", type=Party.RETAIL, phone="9876543210", email="a@x.com", joined=timezone.localdate())

    def invoice(self, store=None, paid=True):
        today = timezone.localdate()
        inv = create_invoice(source=Invoice.SALE, party=self.party, stock_point=store or self.shop, date=today,
                             status=Invoice.PAID if paid else Invoice.LINK_SENT, lines=[{"description": "Dell charger", "qty": 1, "price": 1500}])
        if paid:
            inv.paid_on = today
            inv.save(update_fields=["paid_on"])
        return inv

    def warranty(self, days_left=100, **kw):
        today = timezone.localdate()
        return Warranty.objects.create(party=self.party, section=Warranty.OTHER, item_label="Dell 5420",
                                       start_date=today - timedelta(days=265), end_date=today + timedelta(days=days_left), **kw)


class AutoCreateTests(Base):
    def test_paid_sale_gets_a_warranty_once_and_the_customer_is_told(self):
        inv = self.invoice()
        on_invoice_paid(inv)
        on_invoice_paid(inv)  # paying path may fire twice -- still one warranty
        w = Warranty.objects.get()
        self.assertEqual((w.section, w.invoice_id, w.auto_created), ("Sales", inv.id, True))
        self.assertEqual((w.end_date - w.start_date).days, 365)
        self.assertIn("Dell charger", w.item_label)
        self.assertTrue(Message.objects.filter(party=self.party, body__contains="Your warranty on").exists())

    def test_unpaid_sale_and_switched_off_get_nothing(self):
        on_invoice_paid(self.invoice(paid=False))
        self.assertEqual(Warranty.objects.count(), 0)
        with override_settings(WARRANTY_SALES_DAYS=0):
            on_invoice_paid(self.invoice())
        self.assertEqual(Warranty.objects.count(), 0)

    def test_a_failing_automation_never_breaks_the_payment(self):
        from unittest import mock
        with mock.patch("warranty.services.announce", side_effect=RuntimeError("boom")):
            on_invoice_paid(self.invoice())  # must not raise
        self.assertEqual(Warranty.objects.count(), 0)


class ReminderTests(Base):
    def test_reminders_go_out_once_at_30_and_once_at_7_days(self):
        far, soon, last = self.warranty(100), self.warranty(25), self.warranty(5)
        self.assertEqual(call_command("send_warranty_reminders"), None)
        for w in (far, soon, last):
            w.refresh_from_db()
        self.assertEqual((far.reminded_30_at, bool(soon.reminded_30_at), bool(last.reminded_7_at)), (None, True, True))
        from .services import send_due_reminders
        self.assertEqual(send_due_reminders(), 0)  # nothing new the same day
        self.assertEqual(send_due_reminders(timezone.localdate() + timedelta(days=20)), 1)  # `soon` is now inside 7 days
        self.assertEqual(Message.objects.filter(party=self.party, body__contains="ends").count(), 3)

    def test_expiring_list_summary_and_manual_remind(self):
        self.shop_warranty = self.warranty(10, invoice=self.invoice())
        self.warranty(200, invoice=self.invoice())
        r = self.c.get("/api/warranties/expiring/").json()
        self.assertEqual([w["days_left"] for w in r], [10])
        s = self.c.get("/api/warranties/summary/").json()
        self.assertEqual((s["expiring"], s["active"], s["expired"]), (1, 1, 0))
        self.assertEqual(self.v.post(f"/api/warranties/{self.shop_warranty.id}/remind/").status_code, 403)
        self.assertEqual(self.c.post(f"/api/warranties/{self.shop_warranty.id}/remind/").status_code, 200)
        self.shop_warranty.refresh_from_db()
        self.assertTrue(self.shop_warranty.reminded_30_at)
        self.assertEqual(self.c.post("/api/warranties/send_reminders/").json()["sent"], 0)  # already reminded


class ClaimTests(Base):
    def setUp(self):
        super().setUp()
        self.w = self.warranty(100, invoice=self.invoice())

    def raise_(self, **kw):
        return self.c.post("/api/warranty-claims/", {"warranty": self.w.id, "issue": "Charger stopped working", **kw}, format="json")

    def test_claim_lifecycle_cost_and_customer_messages(self):
        r = self.raise_()
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        self.assertEqual(r.json()["code"], "WC-0001")
        url = f"/api/warranty-claims/{cid}/"
        self.assertEqual(self.c.post(url + "resolve/", {"resolution": "repaired"}, format="json").status_code, 400)  # must approve first
        self.assertEqual(self.c.post(url + "decide/", {"decision": "reject"}, format="json").status_code, 400)       # reason required
        self.assertEqual(self.c.post(url + "decide/", {"decision": "approve"}, format="json").status_code, 200)
        self.assertEqual(self.c.post(url + "decide/", {"decision": "approve"}, format="json").status_code, 400)       # already decided
        r = self.c.post(url + "resolve/", {"resolution": "replaced", "cost": 1200, "note": "New unit"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["status"], r.json()["cost"]), ("resolved", 1200))
        s = self.c.get("/api/warranties/summary/").json()
        self.assertEqual((s["claims_this_month"], s["claim_cost_this_month"], s["open_claims"]), (1, 1200, 0))
        w = self.c.get(f"/api/warranties/{self.w.id}/").json()
        self.assertEqual((w["claim_count"], w["open_claims"]), (1, 0))
        self.assertGreaterEqual(Message.objects.filter(party=self.party, body__contains="WC-0001").count(), 3)

    def test_rules_expired_permission_and_store_scope(self):
        self.assertEqual(self.v.post("/api/warranty-claims/", {"warranty": self.w.id, "issue": "x" * 8}, format="json").status_code, 403)
        old = self.warranty(-5, invoice=self.invoice())
        self.assertEqual(self.c.post("/api/warranty-claims/", {"warranty": old.id, "issue": "Dead on arrival"}, format="json").status_code, 400)
        other_w = self.warranty(50, invoice=self.invoice(store=self.other))
        self.assertEqual(self.c.post("/api/warranty-claims/", {"warranty": other_w.id, "issue": "Dead on arrival"}, format="json").status_code, 400)
        self.assertEqual(self.raise_(repair_code="RPR-9999").status_code, 400)  # unknown repair job
        self.raise_()
        data = self.c.get("/api/warranty-claims/").json()
        self.assertEqual(len(data.get("results", data)), 1)
