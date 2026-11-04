from accounts.models import StaffNotification
from catalog.models import PartStock, Stock
from crmbook_backend.testing import client_for, make_user

from .models import Lead, LeadPartIssue
from .tests import ADMIN, Base


class PartCustodyTests(Base):
    def setUp(self):
        super().setUp()
        self.store_man = make_user("storeman", ADMIN + ("leads.parts",), stock_point=self.shop)
        self.sm = client_for(self.store_man)

    def shelf(self):
        return PartStock.objects.get(part=self.part, stock_point=self.shop).quantity

    def issue(self, lead_id, qty=2, client=None, kind="part", item=None):
        item = item or (self.part.id if kind == "part" else self.variant.id)
        return (client or self.sm).post(f"/api/leads/{lead_id}/issue_parts/", {"kind": kind, "item": item, "qty": qty}, format="json")

    def test_issue_takes_stock_off_the_shelf_in_the_technicians_name_without_invoice(self):
        lead = self.new_lead()
        r = self.issue(lead["id"], 2)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.shelf(), 1)
        iss = LeadPartIssue.objects.get()
        self.assertEqual((iss.technician_id, iss.qty_issued, iss.outstanding), (self.tech.id, 2, 2))
        self.assertEqual(Lead.objects.get(pk=lead["id"]).invoices.count(), 0)
        self.assertEqual(r.json()["parts"][0]["technician_name"], "tech1")

    def test_rules_permission_stock_and_assignment(self):
        lead = self.new_lead()
        self.assertEqual(self.issue(lead["id"], 1, client=self.t).status_code, 403)       # technician can't self-issue
        self.assertEqual(self.issue(lead["id"], 9).status_code, 400)                        # only 3 on the shelf
        self.assertEqual(self.shelf(), 3)
        unassigned = self.new_lead(assigned_to=None)
        self.assertEqual(self.issue(unassigned["id"], 1).status_code, 400)

    def test_used_parts_are_billed_not_deducted_twice_and_leftover_alerts_the_technician(self):
        pk, _ = self.to_approved()
        self.assertEqual(self.issue(pk, 2).status_code, 200)  # shelf 3 -> 1; bill needs 1
        self.t.post(f"/api/leads/{pk}/start/")
        r = self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.shelf(), 1)                       # untouched: the bill used the technician's stock
        iss = LeadPartIssue.objects.get()
        self.assertEqual((iss.qty_used, iss.outstanding), (1, 1))
        line = Lead.objects.get(pk=pk).quotes.first().lines.get(kind="part")
        self.assertEqual(line.custody_qty, 1)
        # settle -> job closes -> the unused one must come back
        inv = Lead.objects.get(pk=pk).invoices.get()
        r = self.a.post(f"/api/leads/{pk}/collect/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Lead.objects.get(pk=pk).status, Lead.CLOSED)
        note = StaffNotification.objects.get(user=self.tech, event_key="parts_return")
        self.assertIn("1 × Charger port", note.body)
        # shows on parts_due as due now, for the technician and the store
        mine = self.t.get("/api/leads/parts_due/").json()
        self.assertEqual((mine["due_now"], mine["mine_due_now"], mine["can_manage"]), (1, 1, False))
        team = self.sm.get("/api/leads/parts_due/").json()
        self.assertEqual(team["due_now"], 1)
        # store takes it back
        r = self.sm.post(f"/api/leads/{pk}/return_parts/", {"issue": iss.id, "qty": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.shelf(), 2)
        self.assertEqual(self.sm.get("/api/leads/parts_due/").json()["due_now"], 0)
        self.assertEqual(self.sm.post(f"/api/leads/{pk}/return_parts/", {"issue": iss.id, "qty": 1}, format="json").status_code, 400)

    def test_cancelled_job_with_unused_parts_alerts_and_return_restores_stock(self):
        lead = self.new_lead()
        self.issue(lead["id"], 3)
        self.assertEqual(self.shelf(), 0)
        self.assertEqual(self.a.post(f"/api/leads/{lead['id']}/cancel/", {"reason": "Client unreachable"}, format="json").status_code, 200)
        self.assertEqual(StaffNotification.objects.filter(user=self.tech, event_key="parts_return").count(), 1)
        iss = LeadPartIssue.objects.get()
        self.assertEqual(self.sm.post(f"/api/leads/{lead['id']}/return_parts/", {"issue": iss.id, "qty": 3}, format="json").status_code, 200)
        self.assertEqual(self.shelf(), 3)
        self.assertEqual(self.issue(lead["id"], 1).status_code, 400)  # no new issues on a finished job

    def test_cancelling_the_bill_hands_used_stock_back_to_the_technician(self):
        pk, _ = self.to_approved()
        self.issue(pk, 1)
        self.t.post(f"/api/leads/{pk}/start/")
        self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        self.assertEqual(LeadPartIssue.objects.get().qty_used, 1)
        inv = Lead.objects.get(pk=pk).invoices.exclude(is_advance=True).get()
        from leads import services
        services.on_lead_invoice_cancelled(inv, self.admin)
        iss = LeadPartIssue.objects.get()
        self.assertEqual((iss.qty_used, iss.outstanding), (0, 1))
        self.assertEqual(self.shelf(), 2)  # shelf untouched by the reversal

    def test_products_work_the_same_and_technician_sees_only_own_holdings(self):
        lead = self.new_lead()
        self.assertEqual(self.issue(lead["id"], 2, kind="product").status_code, 200)
        self.assertEqual(Stock.objects.get(variant=self.variant, stock_point=self.shop).quantity, 3)
        self.assertEqual(self.t.get("/api/leads/parts_due/").json()["holding"], 1)
        self.assertEqual(self.tech2 and client_for(self.tech2).get("/api/leads/parts_due/").json()["holding"], 0)


class WriteOffTests(Base):
    def setUp(self):
        super().setUp()
        # a counter person: may issue and take back, but is not an Admin
        self.counter = make_user("counter", ("leads.view", "leads.assign", "leads.parts"), stock_point=self.shop)
        self.c = client_for(self.counter)

    def test_admin_writes_off_lost_stock_with_a_reason_and_shelf_is_not_credited(self):
        lead = self.new_lead()
        self.c.post(f"/api/leads/{lead['id']}/issue_parts/", {"kind": "part", "item": self.part.id, "qty": 2}, format="json")
        iss = LeadPartIssue.objects.get()
        url = f"/api/leads/{lead['id']}/write_off_parts/"
        body = {"issue": iss.id, "qty": 1, "reason": "Dropped at client site"}
        self.assertEqual(self.c.post(url, body, format="json").status_code, 403)           # counter person: no
        self.assertEqual(self.a.post(url, {**body, "reason": ""}, format="json").status_code, 400)
        self.assertEqual(self.a.post(url, {**body, "qty": 5}, format="json").status_code, 400)
        r = self.a.post(url, body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        iss.refresh_from_db()
        self.assertEqual((iss.qty_written_off, iss.outstanding), (1, 1))
        self.assertEqual(PartStock.objects.get(part=self.part, stock_point=self.shop).quantity, 1)  # 3 - 2 issued; nothing credited
        self.a.post(url, body, format="json")                                                # clear the rest
        self.assertEqual(self.c.get("/api/leads/parts_due/").json()["items"], [])


class PartCostOnBillTests(Base):
    def test_part_line_carries_the_part_cost_or_is_flagged_missing(self):
        from sales.models import InvoiceItem

        self.part.cost = 450
        self.part.save(update_fields=["cost"])
        pk, _ = self.to_approved()
        self.t.post(f"/api/leads/{pk}/start/")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/complete/", {}, format="json").status_code, 200)
        line = InvoiceItem.objects.get(invoice__lead_id=pk, item_kind="part")
        self.assertEqual(line.unit_cost, 450)
