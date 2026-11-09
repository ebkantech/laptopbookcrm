"""A reassigned job: the new technician's timeline starts at their assignment; Admins see it all."""
from .tests import Base
from crmbook_backend.testing import client_for


class TimelineAfterReassignTests(Base):
    def test_new_technician_does_not_see_the_earlier_assignment(self):
        lead = self.new_lead()  # assigned to tech1
        self.assertEqual(client_for(self.tech).post(f"/api/leads/{lead['id']}/check_in/", {"lat": 22.7, "lng": 75.8}, format="json").status_code, 200)
        r = self.a.post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.tech2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        mine = client_for(self.tech2).get(f"/api/leads/{lead['id']}/").json()["events"]
        texts = [e["text"] for e in mine]
        self.assertTrue(texts[0].startswith("Job "), texts)
        self.assertFalse(any("tech1" in t for t in texts), texts)
        self.assertEqual(sum(e["event"] == "assigned" for e in mine), 1)
        self.assertNotIn("checked_in", [e["event"] for e in mine])

        everything = self.a.get(f"/api/leads/{lead['id']}/").json()["events"]
        self.assertEqual(sum(e["event"] == "assigned" for e in everything), 2)
        self.assertGreater(len(everything), len(mine))
