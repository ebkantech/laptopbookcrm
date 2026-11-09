"""Repair approval page works like the rental one: request changes, and "Open my portal"."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Service, StockPoint
from parties.models import Party
from portal.models import PortalInvite
from repairs.models import RepairApproval, RepairTicket
from repairs.services import finalize_estimate, issue_approval_link


class RepairApprovalChangesAndPortalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ap-admin", password="safe-test-password", is_superuser=True)
        self.party = Party.objects.create(name="Asha", type=Party.RETAIL, phone="9876543210", email="asha@example.com", joined=date.today())
        shop = StockPoint.objects.create(slug="shop-ap", name="Shop", kind=StockPoint.SHOP)
        service = Service.objects.create(slug="svc-ap", label="Screen", segment=Service.SOFTWARE, charge=3000)
        self.ticket = RepairTicket.objects.create(code="RPR-AP-1", party=self.party, brand="HP", model_name="Pavilion", stock_point=shop,
                                                  issue="Cracked screen", status=RepairTicket.DIAGNOSING, received=date.today())
        finalize_estimate(self.ticket, self.user, [{"service": service, "description": "Screen", "quantity": 1, "unit_price": 3000}])
        _approval, url, _ = issue_approval_link(self.ticket, self.user)
        self.endpoint = f"/api/public/repair-approvals/{url.rsplit('/', 1)[-1]}/"
        self.public = APIClient()

    def test_request_changes_needs_a_message_and_leaves_nothing_approved(self):
        self.assertEqual(self.public.post(self.endpoint, {"decision": "request_changes"}, format="json").status_code, 400)
        r = self.public.post(self.endpoint, {"decision": "request_changes", "reason": "Please quote a cheaper screen"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "changes_requested")
        self.assertEqual(r.json()["change_request"], "Please quote a cheaper screen")
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.current_estimate.is_approved)
        self.assertEqual(self.ticket.current_estimate.approval_status, RepairApproval.CHANGES_REQUESTED)
        # it can't then be approved on the same link -- staff revise and send a new one
        self.assertEqual(self.public.post(self.endpoint, {"decision": "approve", "consent": True}, format="json").status_code, 409)
        # and staff can send a fresh link
        issue_approval_link(self.ticket, self.user)

    def test_open_my_portal_reuses_or_issues_an_invite(self):
        r = self.public.post(f"{self.endpoint}portal/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        invite = PortalInvite.objects.get(party=self.party)
        self.assertTrue(r.json()["url"].endswith(f"/portal/{invite.token}"))
        self.assertNotIn("asha@example.com", r.json()["email"])  # masked
        again = self.public.post(f"{self.endpoint}portal/", {}, format="json")
        self.assertEqual(again.json()["url"], r.json()["url"])
        self.assertEqual(PortalInvite.objects.filter(party=self.party).count(), 1)

    def test_portal_needs_an_email(self):
        Party.objects.filter(pk=self.party.pk).update(email="")
        r = self.public.post(f"{self.endpoint}portal/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.json()["detail"])

    def test_bad_token(self):
        self.assertEqual(self.public.post("/api/public/repair-approvals/nope/portal/", {}, format="json").status_code, 404)

    def test_other_approval_types_have_the_portal_button_too(self):
        for kind in ("rental-approvals", "repair-order-approvals"):
            self.assertEqual(self.public.post(f"/api/public/{kind}/nope/portal/", {}, format="json").status_code, 404, kind)
