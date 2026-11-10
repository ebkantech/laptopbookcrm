"""Repair jobs are given to staff: the Super Admin to staff of any store, an
Admin to staff of their own store only; assigned jobs are worked by the
assignee, and an Admin can step in."""
from datetime import date

from django.test import TestCase

from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from repairs.models import RepairTicket, RepairTicketEvent

STAFF = ("repairs.view", "repairs.manage")
ADMIN = STAFF + ("repairs.assign", "repairs.approve", "repairs.book")


class AssignmentTests(TestCase):
    def setUp(self):
        self.a = StockPoint.objects.create(slug="a", name="Store A", kind=StockPoint.SHOP)
        self.b = StockPoint.objects.create(slug="b", name="Store B", kind=StockPoint.SHOP)
        self.sa = make_user("sa", superuser=True)
        self.admin_a = make_user("admin-a", ADMIN, stock_point=self.a)
        self.staff_a1 = make_user("staff-a1", STAFF, stock_point=self.a)
        self.staff_a2 = make_user("staff-a2", STAFF, stock_point=self.a)
        self.staff_b = make_user("staff-b", STAFF, stock_point=self.b)
        self.party = Party.objects.create(name="Cust", type=Party.RETAIL, phone="9876543210", joined=date.today())
        self.ticket = RepairTicket.objects.create(code="RPR-9001", party=self.party, brand="Dell", model_name="5420", stock_point=self.a,
                                                  issue="No power", received=date.today())

    def assign(self, user, target, ticket=None):
        return client_for(user).post(f"/api/tickets/{(ticket or self.ticket).id}/assign/", {"assigned_to": target.id if target else None}, format="json")

    def ids(self, user, qs=""):
        data = client_for(user).get(f"/api/tickets/{qs}").json()
        return [t["id"] for t in data.get("results", data)]

    def test_admin_gives_job_to_own_store_staff_only(self):
        r = self.assign(self.admin_a, self.staff_a1)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["assigned_to"], self.staff_a1.id)
        self.assertEqual(self.assign(self.admin_a, self.staff_b).status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to_id, self.staff_a1.id)
        self.assertTrue(RepairTicketEvent.objects.filter(ticket=self.ticket, event_type="assigned").exists())

    def test_super_admin_gives_job_to_any_stores_staff_and_they_see_it(self):
        self.assertNotIn(self.ticket.id, self.ids(self.staff_b))
        self.assertEqual(self.assign(self.sa, self.staff_b).status_code, 200)
        self.assertIn(self.ticket.id, self.ids(self.staff_b))          # from another store's list
        self.assertEqual(self.ids(self.staff_b, "?mine=1"), [self.ticket.id])
        self.assertEqual(client_for(self.staff_b).get(f"/api/tickets/{self.ticket.id}/").status_code, 200)

    def test_staff_cannot_assign_and_cannot_assign_to_non_staff(self):
        self.assertEqual(self.assign(self.staff_a1, self.staff_a2).status_code, 403)
        nobody = make_user("viewer", ("repairs.view",), stock_point=self.a)
        self.assertEqual(self.assign(self.admin_a, nobody).status_code, 400)
        self.assertEqual(self.assign(self.sa, nobody).status_code, 400)

    def test_other_store_admin_cannot_touch_the_ticket(self):
        admin_b = make_user("admin-b", ADMIN, stock_point=self.b)
        self.assertEqual(self.assign(admin_b, self.staff_b).status_code, 404)

    def test_only_the_assignee_progresses_it_but_an_admin_can_step_in(self):
        self.assign(self.admin_a, self.staff_a1)
        move = lambda u: client_for(u).post(f"/api/tickets/{self.ticket.id}/set-stage/", {"status": "Diagnosing"}, format="json")
        self.assertIn(move(self.staff_a2).status_code, (403, 404))       # a colleague can't (the job isn't even visible to them)
        self.assertEqual(move(self.staff_a1).status_code, 200)          # the assignee can
        # assignee away -> Admin takes it over, or hands it to someone else
        r = self.assign(self.admin_a, self.admin_a)
        self.assertEqual(r.status_code, 200)
        ev = RepairTicketEvent.objects.filter(ticket=self.ticket, event_type="assigned").last()
        self.assertTrue(ev.metadata["took_over"])
        self.assertEqual(self.assign(self.admin_a, self.staff_a2).status_code, 200)
        self.assertEqual(move(self.sa).status_code, 200)                 # Super Admin can always act
        self.assertEqual(client_for(self.admin_a).post(f"/api/tickets/{self.ticket.id}/set-stage/", {"status": "Received"}, format="json").status_code, 200)

    def test_unassigned_jobs_wait_and_unassign_works(self):
        r = client_for(self.admin_a).post(f"/api/tickets/{self.ticket.id}/set-stage/", {"status": "Diagnosing"}, format="json")
        self.assertEqual(r.status_code, 400)
        # repair staff don't see a job nobody has given them
        self.assertEqual(client_for(self.staff_a2).post(f"/api/tickets/{self.ticket.id}/set-stage/", {"status": "In progress"}, format="json").status_code, 404)
        self.assign(self.admin_a, self.staff_a1)
        self.assertEqual(self.assign(self.admin_a, None).status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to_id)

    def test_staff_list_follows_the_store_rule(self):
        names = lambda u: {s["id"] for s in client_for(u).get("/api/tickets/staff/").json()}
        self.assertEqual(names(self.admin_a), {self.admin_a.id, self.staff_a1.id, self.staff_a2.id})
        everyone = names(self.sa)
        self.assertTrue({self.staff_a1.id, self.staff_b.id} <= everyone)
        self.assertNotIn(self.sa.id, everyone)  # the Super Admin doesn't take repair jobs

    def test_super_admin_cannot_be_given_or_take_a_job(self):
        self.assertEqual(self.assign(self.admin_a, self.sa).status_code, 400)
        r = self.assign(self.sa, self.sa)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Super Admin", str(r.json()))

    def test_repair_staff_see_only_their_own_jobs(self):
        other = RepairTicket.objects.create(code="RPR-9002", party=self.party, brand="HP", model_name="X", stock_point=self.a,
                                            issue="x", received=date.today())
        self.assign(self.admin_a, self.staff_a1)
        self.assign(self.admin_a, self.staff_a2, ticket=other)
        self.assertEqual(self.ids(self.staff_a1), [self.ticket.id])
        self.assertEqual(self.ids(self.staff_a2), [other.id])
        r = client_for(self.staff_a1).get(f"/api/tickets/{other.id}/")
        self.assertEqual(r.status_code, 404)
        # an unassigned job is not shown to them either
        self.assign(self.admin_a, None)
        self.assertEqual(self.ids(self.staff_a1), [])
        # the Admin still sees the store's jobs
        self.assertTrue({self.ticket.id, other.id} <= set(self.ids(self.admin_a)))


class TimelineAfterReassignTests(AssignmentTests):
    """A reassigned ticket: the new technician's timeline starts at their assignment."""

    def test_new_technician_does_not_see_the_earlier_assignment(self):
        RepairTicketEvent.objects.create(ticket=self.ticket, event_type=RepairTicketEvent.TICKET_CREATED, actor=self.admin_a)
        self.assertEqual(self.assign(self.admin_a, self.staff_a1).status_code, 200)
        RepairTicketEvent.objects.create(ticket=self.ticket, event_type=RepairTicketEvent.DIAGNOSIS_DONE, actor=self.staff_a1)
        self.assertEqual(self.assign(self.admin_a, self.staff_a2).status_code, 200)

        mine = client_for(self.staff_a2).get(f"/api/tickets/{self.ticket.id}/").json()["events"]
        kinds = [e["event_type"] for e in mine]
        self.assertEqual(kinds.count("assigned"), 1, kinds)
        self.assertIn("ticket_created", kinds)
        self.assertNotIn("diagnosis_done", kinds)
        self.assertNotIn("staff-a1", str(mine))

        everything = client_for(self.admin_a).get(f"/api/tickets/{self.ticket.id}/").json()["events"]
        self.assertEqual([e["event_type"] for e in everything].count("assigned"), 2)
