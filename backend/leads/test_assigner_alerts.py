"""The person who gives an on-site job out hears about every step; the technician hears about theirs."""
from accounts.models import StaffNotification
from crmbook_backend.testing import client_for

from .tests import Base


class AssignerAlertTests(Base):
    def subjects(self, user):
        return list(StaffNotification.objects.filter(user=user).order_by("id").values_list("subject", flat=True))

    def test_each_step_goes_back_to_whoever_assigned_it(self):
        lead = self.new_lead()  # created and assigned by the admin client to tech
        self.assertTrue(any("New on-site job" in s for s in self.subjects(self.tech)), self.subjects(self.tech))
        tech = client_for(self.tech)
        self.assertEqual(tech.post(f"/api/leads/{lead['id']}/check_in/", {"lat": 22.7, "lng": 75.8}, format="json").status_code, 200)
        self.assertEqual(tech.post(f"/api/leads/{lead['id']}/diagnose/", {"diagnosis": "Fan clogged"}, format="json").status_code, 200)
        boss = self.subjects(self.admin)
        self.assertTrue(any("reached the site" in s for s in boss), boss)
        self.assertTrue(any("diagnosis recorded" in s for s in boss), boss)
        self.assertTrue(all(s.startswith(lead["code"]) for s in boss))

    def test_no_alert_for_your_own_step(self):
        lead = self.new_lead()
        before = len(self.subjects(self.admin))
        self.a.post(f"/api/leads/{lead['id']}/reschedule/", {"preferred_at": "2030-01-01T10:00:00Z"}, format="json")
        self.a.post(f"/api/leads/{lead['id']}/cancel/", {"reason": "Client not home"}, format="json")
        self.assertEqual(len(self.subjects(self.admin)), before)


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
