from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Part, Service, StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Party

from .models import RepairApproval, RepairRevision, RepairTicket, RepairTicketEvent
from django.test import TestCase


STAFF = ("repairs.view", "repairs.manage")
ADMIN = STAFF + ("repairs.assign", "repairs.approve", "repairs.book")


class Base(TestCase):
    def setUp(self):
        self.store = StockPoint.objects.create(slug="m", name="Main", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="s", name="Second", kind=StockPoint.SHOP)
        self.sa = make_user("sa", superuser=True)
        self.admin = make_user("adm", ADMIN, stock_point=self.store)
        self.staff = make_user("stf", STAFF, stock_point=self.store)
        self.staff2 = make_user("stf2", STAFF, stock_point=self.store)
        self.party = Party.objects.create(name="Cust", type=Party.RETAIL, phone="9876543210", joined=date.today())
        self.service = Service.objects.create(slug="scr", label="Screen", segment=Service.HARDWARE, charge=1500)

    def book(self, user, services=True):
        c = client_for(user)
        r = c.post("/api/tickets/", {
            "party": self.party.pk, "brand": "Dell", "model_name": "L5", "serial": "S1", "stock_point": self.store.pk,
            "issue": "x", "received": date.today().isoformat(), "payment": RepairTicket.FULL,
            "service_ids": [self.service.pk] if services else [],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def approve_current(self, ticket):
        est = ticket.current_estimate
        RepairApproval.objects.create(estimate=est, token_hash=__import__("secrets").token_hex(32), status=RepairApproval.APPROVED,
                                      source=RepairApproval.ADMIN if hasattr(RepairApproval, "ADMIN") else "admin",
                                      expires_at=timezone.now() + timedelta(hours=1), decided_at=timezone.now())


class EstimateAtCreation(Base):
    def test_admin_creation_finalises_and_issues_link(self):
        r = self.book(self.admin)
        self.assertIn("approval", r.data)
        self.assertEqual(r.data["approval"]["total"], 1500)
        t = RepairTicket.objects.get(pk=r.data["id"])
        self.assertEqual(t.current_estimate.total_amount, 1500)
        self.assertTrue(t.current_estimate.approvals.filter(status=RepairApproval.PENDING).exists())

    def test_staff_cannot_book_a_ticket(self):
        c = client_for(self.staff)
        r = c.post("/api/tickets/", {"party": self.party.pk, "brand": "Dell", "model_name": "L5", "serial": "S9", "stock_point": self.store.pk,
                                     "issue": "x", "received": date.today().isoformat(), "payment": RepairTicket.FULL}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_staff_cannot_finalise_or_issue_link(self):
        t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        t.assigned_to = self.staff; t.save()
        c = client_for(self.staff)
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/approval-link/").status_code, 403)
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/finalize-estimate/", {"lines": [{"description": "a", "unit_price": 1}]}, format="json").status_code, 403)


class RevisionFlow(Base):
    def setUp(self):
        super().setUp()
        self.t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        self.approve_current(self.t)
        self.t.assigned_to = self.staff
        self.t.status = RepairTicket.IN_PROGRESS
        self.t.save()
        self.lines = [{"description": "Screen", "quantity": 1, "unit_price": 1500}, {"description": "Board repair", "quantity": 1, "unit_price": 900}]

    def propose(self, user=None):
        return client_for(user or self.staff).post(f"/api/tickets/{self.t.pk}/revise/", {"lines": self.lines, "reason": "Board also dead"}, format="json")

    def test_full_cycle(self):
        r = self.propose()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["applied"])
        self.t.refresh_from_db()
        self.assertEqual(self.t.pending_revision.proposed_total, 2400)
        self.assertEqual(self.t.pending_revision.previous_total, 1500)
        self.assertTrue(self.t.on_hold_reason)
        # still the old approved estimate; only one pending allowed
        self.assertEqual(self.propose().status_code, 400)
        # staff cannot decide
        self.assertEqual(client_for(self.staff).post(f"/api/tickets/{self.t.pk}/decide-revision/", {"decision": "accept"}, format="json").status_code, 403)
        d = client_for(self.admin).post(f"/api/tickets/{self.t.pk}/decide-revision/", {"decision": "accept"}, format="json")
        self.assertEqual(d.status_code, 200, d.data)
        self.assertIn("approval", d.data)
        self.t.refresh_from_db()
        est = self.t.current_estimate
        self.assertEqual((est.version, est.total_amount), (2, 2400))
        self.assertFalse(self.t.has_repair_approval)
        self.assertEqual(self.t.on_hold_reason, "Revised estimate waiting for client approval")
        # can't finish while on hold
        self.assertEqual(client_for(self.staff).post(f"/api/tickets/{self.t.pk}/advance/").status_code, 400)
        # admin approves on behalf -> back to staff
        ok = client_for(self.admin).post(f"/api/tickets/{self.t.pk}/approve-on-behalf/", {"reason": "Client agreed by phone"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.t.refresh_from_db()
        self.assertEqual(self.t.on_hold_reason, "")
        self.assertTrue(self.t.events.filter(event_type=RepairTicketEvent.REVISION_APPROVED).exists())
        self.assertTrue(self.staff.staff_notifications.filter(event_key="repair_revision_approved").exists())
        self.assertEqual(client_for(self.staff).post(f"/api/tickets/{self.t.pk}/advance/").status_code, 200)
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, RepairTicket.READY)
        self.assertEqual(self.t.worked_by, self.staff)

    def test_decline(self):
        self.propose()
        r = client_for(self.admin).post(f"/api/tickets/{self.t.pk}/decide-revision/", {"decision": "decline"}, format="json")
        self.assertEqual(r.status_code, 400)  # needs a note
        r = client_for(self.admin).post(f"/api/tickets/{self.t.pk}/decide-revision/", {"decision": "decline", "note": "Too high"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.t.refresh_from_db()
        self.assertTrue(self.t.has_repair_approval)
        self.assertEqual(self.t.on_hold_reason, "")
        self.assertEqual(self.t.revisions.get().status, RepairRevision.DECLINED)

    def test_other_staff_cannot_propose(self):
        self.assertIn(self.propose(self.staff2).status_code, (403, 404))

    def test_admin_revision_applies_directly(self):
        r = self.propose(self.admin)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["applied"])
        self.assertIn("approval", r.data)
        self.t.refresh_from_db()
        self.assertEqual(self.t.current_estimate.total_amount, 2400)


class StaffReport(Base):
    def make_done(self, staff, hours_to_ready, due_in_days):
        t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        now = timezone.now()
        t.assigned_to = staff; t.worked_by = staff
        t.assigned_at = now - timedelta(hours=hours_to_ready)
        t.ready_at = now
        t.status = RepairTicket.READY
        t.expected = date.today() + timedelta(days=due_in_days)
        t.save()
        return t

    def test_only_admin_and_sa_and_scoped(self):
        self.assertEqual(client_for(self.staff).get("/api/repair-staff-report/").status_code, 403)
        self.assertEqual(client_for(self.admin).get("/api/repair-staff-report/").status_code, 200)

    def test_counts_and_delay(self):
        self.make_done(self.staff, 5, 1)
        late = self.make_done(self.staff, 100, -2)  # promised 2 days ago, finished today -> delayed
        data = client_for(self.admin).get("/api/repair-staff-report/?period=today").data
        row = next(r for r in data["staff"] if r["id"] == self.staff.pk)
        self.assertEqual(row["counts"]["today"], 2)
        self.assertEqual(row["period"]["done"], 2)
        self.assertEqual(row["period"]["delayed"], 1)
        self.assertEqual(row["period"]["on_time"], 1)
        job = next(j for j in row["jobs"] if j["code"] == late.code)
        self.assertTrue(job["delayed"])
        self.assertAlmostEqual(job["hours_taken"], 100, delta=0.2)

    def test_open_overdue_and_admin_scope(self):
        t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        t.assigned_to = self.staff; t.expected = date.today() - timedelta(days=1); t.status = RepairTicket.IN_PROGRESS; t.save()
        far = make_user("far", STAFF, stock_point=self.other)
        a = client_for(self.admin).get("/api/repair-staff-report/").data
        ids = [r["id"] for r in a["staff"]]
        self.assertIn(self.staff.pk, ids); self.assertNotIn(far.pk, ids)
        self.assertEqual(next(r for r in a["staff"] if r["id"] == self.staff.pk)["overdue"], 1)
        s = client_for(self.sa).get("/api/repair-staff-report/").data
        self.assertIn(far.pk, [r["id"] for r in s["staff"]])

    def test_stage_stamps(self):
        t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        self.approve_current(t)
        c = client_for(self.admin)
        c.post(f"/api/tickets/{t.pk}/assign/", {"assigned_to": self.staff.pk}, format="json")
        cs = client_for(self.staff)
        cs.post(f"/api/tickets/{t.pk}/diagnose/", {"note": "ok"}, format="json")
        cs.post(f"/api/tickets/{t.pk}/set-stage/", {"status": "In progress"}, format="json")
        cs.post(f"/api/tickets/{t.pk}/set-stage/", {"status": "Ready for pickup"}, format="json")
        t.refresh_from_db()
        self.assertIsNotNone(t.assigned_at); self.assertIsNotNone(t.started_at); self.assertIsNotNone(t.ready_at)
        self.assertEqual(t.worked_by, self.staff)
        cs.post(f"/api/tickets/{t.pk}/set-stage/", {"status": "In progress"}, format="json")
        t.refresh_from_db()
        self.assertIsNone(t.ready_at)


class ManualPricing(Base):
    def post(self, user, **extra):
        body = {"party": self.party.pk, "brand": "Dell", "model_name": "L5", "serial": "M1", "stock_point": self.store.pk,
                "issue": "x", "received": date.today().isoformat(), "payment": RepairTicket.ADVANCE}
        body.update(extra)
        return client_for(user).post("/api/tickets/", body, format="json")

    def test_typed_lines_and_advance(self):
        from sales.models import Invoice

        r = self.post(self.admin, estimate_lines=[{"description": "Motherboard fix", "quantity": 1, "unit_price": 4800}], advance_amount=1000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["approval"]["total"], 4800)
        t = RepairTicket.objects.get(pk=r.data["id"])
        self.assertEqual(t.services.count(), 0)
        self.assertEqual(t.current_estimate.lines.get().description, "Motherboard fix")
        self.assertEqual(Invoice.objects.get(repair_ticket=t, is_advance=True).total, 1000)

    def test_advance_over_total_rejected_and_none_means_no_invoice(self):
        from sales.models import Invoice

        r = self.post(self.admin, estimate_lines=[{"description": "Fix", "quantity": 1, "unit_price": 500}], advance_amount=900)
        self.assertEqual(r.status_code, 400)
        r = self.post(self.admin, payment=RepairTicket.FULL, estimate_lines=[{"description": "Fix", "quantity": 1, "unit_price": 500}], advance_amount=100)
        self.assertEqual(r.status_code, 201)
        self.assertFalse(Invoice.objects.filter(repair_ticket_id=r.data["id"]).exists())
        r = self.post(self.admin, estimate_lines=[{"description": "Fix", "quantity": 1, "unit_price": 500}], advance_amount=0)
        self.assertFalse(Invoice.objects.filter(repair_ticket_id=r.data["id"]).exists())

    def test_bulk_with_typed_prices(self):
        from sales.models import Invoice

        r = client_for(self.admin).post("/api/repair-orders/", {"party": self.party.pk, "stock_point": self.store.pk, "received": date.today().isoformat(), "payment": "advance",
            "devices": [{"brand": "A", "model_name": "1", "serial": "B1", "issue": "i", "estimate_lines": [{"description": "x", "unit_price": 700}], "advance_amount": 200},
                        {"brand": "B", "model_name": "2", "serial": "B2", "issue": "i", "estimate_lines": [{"description": "y", "unit_price": 300}]}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn("approval", r.data)
        self.assertEqual(sorted(i.total for i in Invoice.objects.filter(is_advance=True)), [200])


class StaffCannotBookOrBill(Base):
    def test_repair_staff_can_work_but_not_book_bill_or_reopen(self):
        r = self.book(self.admin)
        t = RepairTicket.objects.get(pk=r.data["id"])
        self.approve_current(t)
        t.assigned_to = self.staff; t.diagnosed_at = timezone.now(); t.save()
        c = client_for(self.staff)
        body = {"party": self.party.pk, "brand": "D", "model_name": "m", "serial": "Z9", "stock_point": self.store.pk, "issue": "x", "received": date.today().isoformat(), "payment": "full"}
        self.assertEqual(c.post("/api/tickets/", body, format="json").status_code, 403)
        self.assertEqual(c.post("/api/repair-orders/", {}, format="json").status_code, 403)
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/settle/").status_code, 403)
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/reopen/", {}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"/api/tickets/{t.pk}/", {"issue": "changed"}, format="json").status_code, 403)
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/set-stage/", {"status": "Delivered"}, format="json").status_code, 400)
        # ...but does the job and sends it back
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/set-stage/", {"status": "In progress"}, format="json").status_code, 200)
        self.assertEqual(c.post(f"/api/tickets/{t.pk}/advance/").status_code, 200)


class DiagnosisGate(Base):
    def setUp(self):
        super().setUp()
        self.t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        self.approve_current(self.t)
        client_for(self.admin).post(f"/api/tickets/{self.t.pk}/assign/", {"assigned_to": self.staff.pk}, format="json")

    def start(self, user, **extra):
        return client_for(user).post(f"/api/tickets/{self.t.pk}/set-stage/", {"status": "In progress", **extra}, format="json")

    def test_work_cannot_start_until_staff_report_diagnosis(self):
        self.assertTrue(client_for(self.admin).get(f"/api/tickets/{self.t.pk}/").data["awaiting_diagnosis"])
        for user in (self.admin, self.staff):
            r = self.start(user)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.data["code"], "awaiting_diagnosis")
        self.assertEqual(client_for(self.admin).post(f"/api/tickets/{self.t.pk}/advance/").status_code, 200)  # Received -> Diagnosing is fine
        self.assertEqual(self.start(self.staff).status_code, 400)

    def test_diagnosis_with_estimate_ok_unlocks_work(self):
        r = client_for(self.staff).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": "Board is fine, needs reseating RAM", "estimate_ok": True}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.t.refresh_from_db()
        self.assertEqual((self.t.status, self.t.diagnosed_by), ("Diagnosing", self.staff))
        self.assertFalse(r.data["ticket"]["awaiting_diagnosis"])
        self.assertEqual(self.start(self.admin).status_code, 200)
        # reporting twice is refused
        self.assertEqual(client_for(self.staff).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": "again"}, format="json").status_code, 400)

    def test_admin_and_super_admin_cannot_report_the_diagnosis(self):
        for user in (self.admin, self.sa):
            r = client_for(user).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": "x"}, format="json")
            self.assertEqual(r.status_code, 403)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.diagnosed_at)

    def test_diagnosis_needs_a_note_and_the_assigned_staff(self):
        self.assertEqual(client_for(self.staff).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": ""}, format="json").status_code, 400)
        self.assertIn(client_for(self.staff2).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": "x"}, format="json").status_code, (403, 404))

    def test_estimate_change_goes_to_admin_and_holds_work(self):
        r = client_for(self.staff).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": "Board dead", "estimate_ok": False,
                                        "lines": [{"description": "Board", "quantity": 1, "unit_price": 3000}]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["applied"])
        self.t.refresh_from_db()
        self.assertEqual(self.t.pending_revision.proposed_total, 3000)
        self.assertEqual(self.start(self.admin).status_code, 400)  # revision unresolved
        client_for(self.admin).post(f"/api/tickets/{self.t.pk}/decide-revision/", {"decision": "accept"}, format="json")
        self.assertEqual(self.start(self.admin).status_code, 400)  # client hasn't approved the new price
        client_for(self.admin).post(f"/api/tickets/{self.t.pk}/approve-on-behalf/", {"reason": "agreed on phone"}, format="json")
        self.assertEqual(self.start(self.admin).status_code, 200)

    def test_estimate_change_requires_lines(self):
        r = client_for(self.staff).post(f"/api/tickets/{self.t.pk}/diagnose/", {"note": "x", "estimate_ok": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.diagnosed_at)

    def test_admin_can_override_with_a_reason_staff_cannot(self):
        self.assertEqual(self.start(self.staff, override_reason="please").status_code, 400)
        self.assertEqual(self.start(self.admin, override_reason="").status_code, 400)
        self.assertEqual(self.start(self.admin, override_reason="Staff on leave, issue obvious").status_code, 200)
        ev = self.t.events.filter(event_type=RepairTicketEvent.STAGE_CHANGED).order_by("-id")
        self.assertTrue(any(e.metadata.get("override") for e in ev))

    def test_unassigned_ticket_is_not_gated(self):
        t = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])
        self.approve_current(t)
        self.assertEqual(client_for(self.admin).post(f"/api/tickets/{t.pk}/set-stage/", {"status": "In progress"}, format="json").status_code, 200)
