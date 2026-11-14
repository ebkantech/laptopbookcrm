"""The person who gives an on-site job out hears about every step; the technician hears about theirs."""
from django.db import transaction
from rest_framework.test import APIClient

from accounts.models import StaffNotification
from crmbook_backend.testing import client_for

from . import services
from .models import Lead
from .tests import Base


class AssignerAlertTests(Base):
    """
    Alerts go out on transaction commit (crmbook_backend.notify._after_commit).
    TestCase never commits, so each request runs inside
    captureOnCommitCallbacks(execute=True) -- the alerts then fire exactly as
    they would after a real commit.
    """

    def subjects(self, user):
        return list(StaffNotification.objects.filter(user=user).order_by("id").values_list("subject", flat=True))

    def post(self, client, url, data=None):
        with self.captureOnCommitCallbacks(execute=True):
            r = client.post(url, data or {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r

    def new_lead(self, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return super().new_lead(**extra)

    def test_each_step_goes_back_to_whoever_assigned_it(self):
        lead = self.new_lead()  # created and assigned by the admin client to tech
        self.assertTrue(any("New on-site job" in s for s in self.subjects(self.tech)), self.subjects(self.tech))
        tech = client_for(self.tech)
        self.post(tech, f"/api/leads/{lead['id']}/check_in/", {"lat": 22.7, "lng": 75.8})
        self.post(tech, f"/api/leads/{lead['id']}/diagnose/", {"diagnosis": "Fan clogged"})
        boss = self.subjects(self.admin)
        self.assertTrue(any("reached the site" in s for s in boss), boss)
        self.assertTrue(any("diagnosis recorded" in s for s in boss), boss)
        self.assertTrue(all(s.startswith(lead["code"]) for s in boss))

    def test_no_alert_for_your_own_step(self):
        lead = self.new_lead()  # the admin assigned it, so the admin is the assigner
        before = self.subjects(self.admin)
        tech_before = self.subjects(self.tech)
        self.post(self.a, f"/api/leads/{lead['id']}/reschedule/", {"preferred_at": "2030-01-01T10:00:00Z"})
        self.post(self.a, f"/api/leads/{lead['id']}/cancel/", {"reason": "Client not home"})
        # the steps really happened...
        self.assertEqual(Lead.objects.get(pk=lead["id"]).status, Lead.CANCELLED)
        # ...but the assigner did them, so nobody's bell changed
        self.assertEqual(self.subjects(self.admin), before)
        self.assertFalse(any("cancelled" in s for s in self.subjects(self.admin)))
        self.assertEqual(self.subjects(self.tech), tech_before)
        # control: the same kind of step by someone else DOES reach the assigner
        other = self.new_lead()
        self.post(self.t, f"/api/leads/{other['id']}/check_in/", {})
        self.assertEqual(len(self.subjects(self.admin)), len(before) + 1)

    def test_rolled_back_assignment_sends_nothing(self):
        lead = Lead.objects.get(pk=self.new_lead(assigned_to=None)["id"])
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    services.assign(lead, self.tech, self.admin)
                    raise RuntimeError("something later in the request failed")
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])
        self.assertEqual(self.subjects(self.tech), [])
        self.assertIsNone(Lead.objects.get(pk=lead.pk).assigned_to_id)

    def test_committed_assignment_alerts_the_technician_once(self):
        lead = self.new_lead(assigned_to=None)
        self.post(self.a, f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.tech.id})
        self.assertEqual([s for s in self.subjects(self.tech) if "New on-site job" in s],
                         [f"New on-site job {lead['code']} -- {self.party.name}"])
        # assigning the same technician again isn't a new job for them
        self.post(self.a, f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.tech.id})
        self.assertEqual(sum("New on-site job" in s for s in self.subjects(self.tech)), 1)
        # a different technician does get told
        self.post(self.a, f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.tech2.id})
        self.assertEqual(sum("New on-site job" in s for s in self.subjects(self.tech2)), 1)

    def test_bill_decisions_reach_assigner_and_technician(self):
        lead = self.new_lead()
        pk = lead["id"]
        self.post(self.t, f"/api/leads/{pk}/check_in/", {})
        self.post(self.t, f"/api/leads/{pk}/diagnose/", {"diagnosis": "DC jack burnt"})
        self.post(self.t, f"/api/leads/{pk}/quote/", {"lines": self.lines()})
        token = self.post(self.t, f"/api/leads/{pk}/send_link/").json()["approval_url"].rsplit("/", 1)[1]
        self.post(APIClient(), f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True})
        self.assertEqual(sum("bill approved" in s for s in self.subjects(self.admin)), 1, self.subjects(self.admin))
        self.assertEqual(sum("bill approved -- start the work" in s for s in self.subjects(self.tech)), 1, self.subjects(self.tech))

    def test_self_assigned_job_gets_one_alert_per_bill_decision(self):
        lead = self.new_lead(assigned_to=self.admin.id)  # assigner and technician are the same person
        pk = lead["id"]
        self.post(self.a, f"/api/leads/{pk}/check_in/", {})
        self.post(self.a, f"/api/leads/{pk}/diagnose/", {"diagnosis": "DC jack burnt"})
        self.post(self.a, f"/api/leads/{pk}/quote/", {"lines": self.lines()})
        token = self.post(self.a, f"/api/leads/{pk}/send_link/").json()["approval_url"].rsplit("/", 1)[1]
        before = len(self.subjects(self.admin))
        self.post(APIClient(), f"/api/public/lead-approvals/{token}/", {"decision": "approve", "consent": True})
        new = self.subjects(self.admin)[before:]
        self.assertEqual(new, [f"{lead['code']}: bill approved -- start the work"])


class CheckInIsTheEngineersTests(Base):
    """Only the engineer the job is assigned to sees / uses "I've reached the site"."""

    def test_admin_and_super_admin_cannot_check_in_for_the_engineer(self):
        from crmbook_backend.testing import make_user

        lead = self.new_lead()  # assigned to tech
        boss = client_for(make_user("ci-boss", (), superuser=True))
        for who in (self.a, boss):
            self.assertNotIn("check_in", who.get(f"/api/leads/{lead['id']}/").json()["actions"])
            r = who.post(f"/api/leads/{lead['id']}/check_in/", {}, format="json")
            self.assertEqual(r.status_code, 403, r.content)
            self.assertIn("Only the engineer", r.json()["detail"])
        self.assertIn("check_in", self.t.get(f"/api/leads/{lead['id']}/").json()["actions"])
        self.assertEqual(self.t.post(f"/api/leads/{lead['id']}/check_in/", {}, format="json").status_code, 200)
