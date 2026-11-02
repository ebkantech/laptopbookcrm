from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Part, PartStock, Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from sales.models import Invoice

from . import services
from .models import Lead, LeadApproval, LeadEvent

ADMIN = ("leads.view", "leads.create", "leads.assign", "leads.work", "leads.quote", "leads.approve", "leads.collect", "leads.manage")
TECH = ("leads.view", "leads.work", "leads.quote", "leads.collect")


class Base(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="s1", name="Main Shop", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="s2", name="Other Shop", kind=StockPoint.SHOP)
        self.admin = make_user("admin1", ADMIN, stock_point=self.shop)
        self.tech = make_user("tech1", TECH, stock_point=self.shop)
        self.tech2 = make_user("tech2", TECH, stock_point=self.shop)
        self.party = Party.objects.create(name="Ravi Traders", type=Party.RETAIL, phone="9876543210", joined=timezone.localdate())
        self.part = Part.objects.create(slug="ssd-ch", name="Charger port")
        PartStock.objects.create(part=self.part, stock_point=self.shop, quantity=3)
        product = Product.objects.create(brand="Kingston", model_name="A400 480GB", product_code="VC-ACC-9001", category="ssd")
        self.variant = Variant.objects.create(product=product, code="KG-480", spec="480GB", mrp=3000, sell_price=2500, cost=1800)
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=5)
        self.a, self.t = client_for(self.admin), client_for(self.tech)

    def new_lead(self, **extra):
        body = {"party": self.party.id, "stock_point": self.shop.id, "site_address": "12 MG Road, Indore", "issue": "Laptop not charging",
                "device": "Dell 5420", "visit_charge": 300, "assigned_to": self.tech.id, **extra}
        r = self.a.post("/api/leads/", body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def lines(self, qty=1):
        return [{"kind": "labour", "description": "Repair charging circuit", "qty": 1, "price": 800},
                {"kind": "part", "part": self.part.id, "qty": qty, "price": 450},
                {"kind": "product", "variant": self.variant.id, "qty": 1, "price": 2500}]

    def to_approved(self, via_link=True):
        lead = self.new_lead()
        pk = lead["id"]
        self.assertEqual(self.t.post(f"/api/leads/{pk}/check_in/", {"lat": 22.7, "lng": 75.8}, format="json").status_code, 200)
        self.assertEqual(self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "DC jack burnt"}, format="json").status_code, 200)
        self.assertEqual(self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json").status_code, 200)
        r = self.t.post(f"/api/leads/{pk}/send_link/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        token = r.json()["approval_url"].rsplit("/", 1)[1]
        if via_link:
            r = APIClient().post(f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
        return pk, token


class FlowTests(Base):
    def test_full_happy_path_with_advance_and_stock(self):
        pk, _ = self.to_approved()
        self.assertEqual(Lead.objects.get(pk=pk).status, "approved")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/advance/", {"amount": 1000}, format="json").status_code, 403)  # technicians can't ask
        r = self.a.post(f"/api/leads/{pk}/advance/", {"amount": 1000}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        adv = Invoice.objects.get(lead_id=pk, is_advance=True)
        self.assertEqual(self.t.post(f"/api/leads/{pk}/collect/", {"invoice": adv.id, "pay_method": "Cash"}, format="json").status_code, 200)
        self.assertEqual(Lead.objects.get(pk=pk).status, "approved")  # advance doesn't close it
        self.assertEqual(self.t.post(f"/api/leads/{pk}/start/", {}, format="json").status_code, 200)
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity, 5)  # nothing deducted yet
        r = self.t.post(f"/api/leads/{pk}/complete/", {"notes": "Replaced DC jack"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity, 4)
        self.assertEqual(PartStock.objects.get(part=self.part).quantity, 2)
        bill = services.bill_invoice(Lead.objects.get(pk=pk))
        self.assertEqual(bill.source, "onsite")
        # visit 300 + labour 800 + part 450 + product 2500 - advance 1000
        self.assertEqual(bill.total, 300 + 800 + 450 + 2500 - 1000)
        r = self.t.post(f"/api/leads/{pk}/collect/", {"pay_method": "UPI", "payment_reference": "UTR123"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        lead = Lead.objects.get(pk=pk)
        self.assertEqual(lead.status, "closed")
        self.assertIsNotNone(lead.checked_out_at)

    def test_no_work_before_approval(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "x y z"}, format="json")
        self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json")
        r = self.t.post(f"/api/leads/{pk}/start/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_client_rejection_bills_the_visit_only(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "board dead"}, format="json")
        self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json")
        token = self.t.post(f"/api/leads/{pk}/send_link/", {}, format="json").json()["approval_url"].rsplit("/", 1)[1]
        r = APIClient().post(f"/api/public/lead-approvals/{token}/", {"decision": "reject", "reason": "too costly"}, format="json")
        self.assertEqual(r.status_code, 200)
        obj = Lead.objects.get(pk=pk)
        self.assertEqual(obj.status, "rejected")
        inv = Invoice.objects.get(lead=obj)
        self.assertEqual(inv.total, 300)
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity, 5)
        self.t.post(f"/api/leads/{pk}/collect/", {"pay_method": "Cash"}, format="json")
        obj.refresh_from_db()
        self.assertIsNotNone(obj.checked_out_at)
        self.assertEqual(obj.status, "rejected")

    def test_rejection_with_no_visit_charge_checks_out_straight_away(self):
        lead = self.new_lead(visit_charge=0)
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "board dead"}, format="json")
        self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json")
        token = self.t.post(f"/api/leads/{pk}/send_link/", {}, format="json").json()["approval_url"].rsplit("/", 1)[1]
        APIClient().post(f"/api/public/lead-approvals/{token}/", {"decision": "reject"}, format="json")
        self.assertFalse(Invoice.objects.filter(lead_id=pk).exists())
        self.assertIsNotNone(Lead.objects.get(pk=pk).checked_out_at)

    def test_admin_approves_on_behalf_needs_reason_and_permission(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "board dead"}, format="json")
        # admin prepares the bill on the technician's behalf
        r = self.a.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["quote"]["on_behalf"])
        self.assertEqual(self.t.post(f"/api/leads/{pk}/approve/", {"reason": "client said ok"}, format="json").status_code, 403)
        self.assertEqual(self.a.post(f"/api/leads/{pk}/approve/", {"reason": " "}, format="json").status_code, 400)
        r = self.a.post(f"/api/leads/{pk}/approve/", {"reason": "Client agreed on phone"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        ap = LeadApproval.objects.get(lead_id=pk, status="approved")
        self.assertEqual(ap.source, "admin")
        self.assertEqual(ap.reason, "Client agreed on phone")

    def test_revising_an_approved_bill_needs_fresh_approval(self):
        pk, token = self.to_approved()
        self.assertEqual(self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines(qty=2)}, format="json").status_code, 200)
        lead = Lead.objects.get(pk=pk)
        self.assertEqual(lead.status, "diagnosed")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/start/", {}, format="json").status_code, 400)
        r = APIClient().get(f"/api/public/lead-approvals/{token}/")
        self.assertEqual(r.status_code, 410)  # the old link is withdrawn
        self.assertEqual(lead.quotes.count(), 2)

    def test_insufficient_stock_blocks_completion_and_changes_nothing(self):
        pk, _ = self.to_approved()
        PartStock.objects.filter(part=self.part).update(quantity=0)
        self.t.post(f"/api/leads/{pk}/start/", {}, format="json")
        r = self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Not enough stock", str(r.json()))
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity, 5)
        self.assertFalse(Invoice.objects.filter(lead_id=pk, is_advance=False).exists())
        self.assertEqual(Lead.objects.get(pk=pk).status, "in_work")

    def test_cancelling_the_bill_restores_stock_and_reopens_work(self):
        pk, _ = self.to_approved()
        self.t.post(f"/api/leads/{pk}/start/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        inv = services.bill_invoice(Lead.objects.get(pk=pk))
        from sales.services import cancel_invoice
        cancel_invoice(inv, self.admin, "wrong part")
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity, 5)
        self.assertEqual(PartStock.objects.get(part=self.part).quantity, 3)
        self.assertEqual(Lead.objects.get(pk=pk).status, "in_work")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/complete/", {}, format="json").status_code, 200)
        self.assertEqual(Stock.objects.get(variant=self.variant).quantity, 4)

    def test_close_on_credit_is_admin_only_with_reason(self):
        pk, _ = self.to_approved()
        self.t.post(f"/api/leads/{pk}/start/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/close_credit/", {"reason": "x"}, format="json").status_code, 403)
        self.assertEqual(self.a.post(f"/api/leads/{pk}/close_credit/", {}, format="json").status_code, 400)
        self.assertEqual(self.a.post(f"/api/leads/{pk}/close_credit/", {"reason": "Pays Friday"}, format="json").status_code, 200)
        lead = Lead.objects.get(pk=pk)
        self.assertTrue(lead.closed_on_credit)
        self.assertEqual(lead.status, "closed")

    def test_advance_covering_whole_bill_closes_the_job(self):
        pk, _ = self.to_approved()
        self.a.post(f"/api/leads/{pk}/advance/", {"amount": 4050}, format="json")
        adv = Invoice.objects.get(lead_id=pk, is_advance=True)
        self.a.post(f"/api/leads/{pk}/collect/", {"invoice": adv.id, "pay_method": "Cash"}, format="json")
        self.t.post(f"/api/leads/{pk}/start/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        lead = Lead.objects.get(pk=pk)
        self.assertEqual(lead.status, "closed")
        self.assertEqual(services.bill_invoice(lead).total, 0)

    def test_unpaid_advance_is_dropped_at_final_bill(self):
        pk, _ = self.to_approved()
        self.a.post(f"/api/leads/{pk}/advance/", {"amount": 500}, format="json")
        self.t.post(f"/api/leads/{pk}/start/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/complete/", {}, format="json")
        self.assertEqual(Invoice.objects.get(lead_id=pk, is_advance=True).status, "Cancelled")
        self.assertEqual(services.bill_invoice(Lead.objects.get(pk=pk)).total, 4050)

    def test_advance_asked_at_creation_raises_an_invoice_and_is_optional(self):
        with_adv = self.new_lead(advance_amount=500)
        inv = Invoice.objects.get(lead_id=with_adv["id"])
        self.assertTrue(inv.is_advance)
        self.assertEqual(inv.total, 500)
        without = self.new_lead()
        self.assertFalse(Invoice.objects.filter(lead_id=without["id"]).exists())

    def test_technician_does_not_get_the_advance_button(self):
        lead = self.new_lead()
        self.assertNotIn("advance", self.t.get(f"/api/leads/{lead['id']}/").json()["actions"])
        self.assertIn("advance", self.a.get(f"/api/leads/{lead['id']}/").json()["actions"])

    def test_unfixable_on_site_goes_to_the_store_as_a_repair_ticket(self):
        from repairs.models import RepairTicket

        lead = self.new_lead(advance_amount=500)
        pk = lead["id"]
        adv = Invoice.objects.get(lead_id=pk, is_advance=True)
        self.a.post(f"/api/leads/{pk}/collect/", {"invoice": adv.id, "pay_method": "Cash"}, format="json")
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "Motherboard fault, needs bench repair"}, format="json")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/to_store/", {}, format="json").status_code, 400)  # reason needed
        r = self.t.post(f"/api/leads/{pk}/to_store/", {"reason": "Needs chip-level repair"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["status"], "to_store")
        ticket = RepairTicket.objects.get(pk=body["repair_ticket"])
        self.assertEqual(ticket.stock_point_id, self.shop.id)
        self.assertEqual(ticket.advance_paid, 500)          # advance carried over
        self.assertEqual(ticket.status, "Received")
        self.assertIn("Motherboard fault", ticket.issue)
        self.assertEqual(Invoice.objects.get(lead_id=pk, is_advance=False).total, 300)  # visit charge billed
        self.assertEqual(self.t.post(f"/api/leads/{pk}/start/", {}, format="json").status_code, 400)
        self.assertEqual(self.t.post(f"/api/leads/{pk}/to_store/", {"reason": "again"}, format="json").status_code, 400)
        r = self.t.post(f"/api/leads/{pk}/collect/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        lead = Lead.objects.get(pk=pk)
        self.assertEqual(lead.status, "to_store")
        self.assertIsNotNone(lead.checked_out_at)

    def test_to_store_without_visit_charge_and_unpaid_advance_dropped(self):
        lead = self.new_lead(advance_amount=500)
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        r = self.t.post(f"/api/leads/{pk}/to_store/", {"reason": "Parts needed", "charge_visit": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Invoice.objects.get(lead_id=pk).status, "Cancelled")
        self.assertIsNotNone(Lead.objects.get(pk=pk).checked_out_at)

    def test_cancel_with_visit_charge(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.assertEqual(self.t.post(f"/api/leads/{pk}/cancel/", {}, format="json").status_code, 400)
        r = self.t.post(f"/api/leads/{pk}/cancel/", {"reason": "Client not home", "charge_visit": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Invoice.objects.get(lead_id=pk).total, 300)

    def test_timeline_records_each_step(self):
        pk, _ = self.to_approved()
        events = list(LeadEvent.objects.filter(lead_id=pk).values_list("event", flat=True))
        for e in ("created", "assigned", "checked_in", "diagnosed", "quote_saved", "link_issued", "approved"):
            self.assertIn(e, events)


class ApprovalLinkTests(Base):
    def issue(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "board dead"}, format="json")
        self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json")
        return pk, self.t.post(f"/api/leads/{pk}/send_link/", {}, format="json").json()["approval_url"].rsplit("/", 1)[1]

    def test_public_page_shows_bill_without_internal_data(self):
        pk, token = self.issue()
        r = APIClient().get(f"/api/public/lead-approvals/{token}/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 4050)
        self.assertEqual(body["lines"][0]["kind"], "visit")
        self.assertNotIn("token_hash", body)
        self.assertEqual(r["Cache-Control"], "no-store, private")

    def test_consent_required_to_approve(self):
        pk, token = self.issue()
        r = APIClient().post(f"/api/public/lead-approvals/{token}/", {"decision": "approve"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_link_expires_after_24_hours(self):
        pk, token = self.issue()
        LeadApproval.objects.filter(lead_id=pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(APIClient().get(f"/api/public/lead-approvals/{token}/").status_code, 410)
        r = APIClient().post(f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True}, format="json")
        self.assertEqual(r.status_code, 410)
        self.assertEqual(Lead.objects.get(pk=pk).status, "awaiting_approval")

    def test_unknown_token_is_404_and_double_decision_conflicts(self):
        pk, token = self.issue()
        self.assertEqual(APIClient().get("/api/public/lead-approvals/nope/").status_code, 404)
        c = APIClient()
        self.assertEqual(c.post(f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True}, format="json").status_code, 200)
        self.assertEqual(c.post(f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True}, format="json").status_code, 200)
        self.assertEqual(c.post(f"/api/public/lead-approvals/{token}/", {"decision": "reject"}, format="json").status_code, 409)

    def test_change_request_sends_job_back_to_staff(self):
        pk, token = self.issue()
        c = APIClient()
        self.assertEqual(c.post(f"/api/public/lead-approvals/{token}/", {"decision": "request_changes"}, format="json").status_code, 400)
        r = c.post(f"/api/public/lead-approvals/{token}/", {"decision": "request_changes", "reason": "Skip the SSD"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Lead.objects.get(pk=pk).status, "diagnosed")
        # a revised bill and a new link
        lines = self.lines()[:2]
        self.assertEqual(self.t.post(f"/api/leads/{pk}/quote/", {"lines": lines}, format="json").status_code, 200)
        r = self.t.post(f"/api/leads/{pk}/send_link/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_decision_records_ip_and_user_agent(self):
        pk, token = self.issue()
        APIClient().post(f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True}, format="json",
                         HTTP_USER_AGENT="TestBrowser/1", REMOTE_ADDR="10.1.2.3")
        ap = LeadApproval.objects.get(lead_id=pk, status="approved")
        self.assertEqual(ap.source, "customer")
        self.assertEqual(ap.decided_ip, "10.1.2.3")
        self.assertEqual(ap.decided_user_agent, "TestBrowser/1")


class AccessTests(Base):
    def test_technician_sees_only_own_jobs_and_cannot_touch_others(self):
        mine = self.new_lead()
        theirs = self.new_lead(assigned_to=self.tech2.id)
        ids = [l["id"] for l in self.t.get("/api/leads/").json().get("results", self.t.get("/api/leads/").json())]
        self.assertEqual(ids, [mine["id"]])
        self.assertEqual(self.t.get(f"/api/leads/{theirs['id']}/").status_code, 404)
        self.assertEqual(self.t.post(f"/api/leads/{theirs['id']}/check_in/", {}, format="json").status_code, 404)

    def test_technicians_belong_to_no_store_and_super_admin_can_assign_any(self):
        roamer = make_user("roamer", TECH)  # no store at all
        boss = make_user("boss", (), superuser=True)
        lead = self.new_lead(assigned_to=None)
        listed = [t["id"] for t in client_for(boss).get("/api/leads/technicians/").json()]
        self.assertIn(roamer.id, listed)
        self.assertIn(self.tech.id, listed)
        r = client_for(boss).post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": roamer.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        c = client_for(roamer)
        self.assertEqual([l["id"] for l in c.get("/api/leads/").json().get("results", c.get("/api/leads/").json())], [lead["id"]])
        self.assertEqual(c.post(f"/api/leads/{lead['id']}/check_in/", {}, format="json").status_code, 200)
        # a technician from another store works too, and a store admin still sees only their store
        far = make_user("far", TECH, stock_point=self.other)
        self.a.post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": far.id}, format="json")
        self.assertEqual(Lead.objects.get(pk=lead["id"]).assigned_to_id, far.id)
        outsider = make_user("outsider2", ADMIN, stock_point=self.other)
        self.assertEqual(client_for(outsider).get(f"/api/leads/{lead['id']}/").status_code, 404)
        self.assertEqual(client_for(boss).get(f"/api/leads/{lead['id']}/").status_code, 200)

    def test_staff_without_a_store_still_see_jobs_given_to_them(self):
        lead = self.new_lead(assigned_to=None)
        rohit = make_user("rohit", TECH + ("leads.create", "leads.assign"))  # store-wide perms, no store
        self.a.post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": rohit.id}, format="json")
        c = client_for(rohit)
        data = c.get("/api/leads/").json()
        self.assertEqual([l["id"] for l in data.get("results", data)], [lead["id"]])
        self.assertEqual(c.get(f"/api/leads/{lead['id']}/").status_code, 200)

    def test_technician_cannot_create_assign_or_edit(self):
        body = {"party": self.party.id, "stock_point": self.shop.id, "site_address": "12 MG Road, Indore", "issue": "Not booting"}
        self.assertEqual(self.t.post("/api/leads/", body, format="json").status_code, 403)
        lead = self.new_lead()
        self.assertEqual(self.t.post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.tech2.id}, format="json").status_code, 403)
        self.assertEqual(self.t.patch(f"/api/leads/{lead['id']}/", {"visit_charge": 0}, format="json").status_code, 403)

    def test_other_store_is_isolated(self):
        lead = self.new_lead()
        outsider = make_user("outsider", ADMIN, stock_point=self.other)
        c = client_for(outsider)
        self.assertEqual(c.get(f"/api/leads/{lead['id']}/").status_code, 404)
        body = {"party": self.party.id, "stock_point": self.shop.id, "site_address": "12 MG Road, Indore", "issue": "Not booting"}
        self.assertEqual(c.post("/api/leads/", body, format="json").status_code, 403)

    def test_unassigned_user_reaches_nothing(self):
        u = make_user("nostore", ADMIN)
        self.assertEqual(client_for(u).post("/api/leads/", {"party": self.party.id, "stock_point": self.shop.id,
                         "site_address": "12 MG Road, Indore", "issue": "Not booting"}, format="json").status_code, 403)

    def test_validation(self):
        body = {"party": self.party.id, "stock_point": self.shop.id, "site_address": "x", "issue": "no"}
        r = self.a.post("/api/leads/", body, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("site_address", r.json())
        self.assertIn("issue", r.json())
        r = self.a.post("/api/leads/", {**body, "site_address": "12 MG Road, Indore", "issue": "Dead", "assigned_to": self.admin.id + 999}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_quote_line_validation(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "board dead"}, format="json")
        for bad in ([], [{"kind": "labour", "description": "x", "qty": 0, "price": 10}],
                    [{"kind": "labour", "description": "x", "qty": 1, "price": -5}],
                    [{"kind": "part", "qty": 1, "price": 5}], [{"kind": "wat", "description": "x", "qty": 1, "price": 5}],
                    [{"kind": "labour", "description": "", "qty": 1, "price": 5}]):
            self.assertEqual(self.t.post(f"/api/leads/{pk}/quote/", {"lines": bad}, format="json").status_code, 400, bad)

    def test_invoice_list_shows_onsite_source(self):
        pk, _ = self.to_approved()
        self.a.post(f"/api/leads/{pk}/advance/", {"amount": 500}, format="json")
        from sales.serializers import InvoiceSerializer
        inv = Invoice.objects.get(lead_id=pk)
        data = InvoiceSerializer(inv).data
        self.assertEqual(data["source"], "onsite")
        self.assertIn("Advance", data["reference"])
