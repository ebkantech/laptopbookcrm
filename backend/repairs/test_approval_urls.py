"""Every customer- and staff-facing link Django builds points at the Next.js
Customer Portal behind settings.PUBLIC_FRONTEND_URL: repair, repair-order,
lead and rental approval, and staff set-password. Tokens, expiry and the
public APIs behind those pages are unchanged."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.staff import SETUP_LINK_HOURS, setup_link, setup_tokens
from catalog.models import Service, StockPoint
from crmbook_backend.testing import client_for, make_user
from leads.models import Lead, LeadApproval
from leads.services import build_approval_url as build_lead_approval_url
from leads.tests import Base as LeadBase
from parties.models import Message, Party
from rentals.services import build_approval_url as build_rental_approval_url
from repairs.models import RepairApproval, RepairTicket
from repairs.services import (
    approval_token_hash,
    build_approval_url,
    build_order_approval_url,
    finalize_estimate,
    issue_approval_link,
    send_approval_link_whatsapp,
)

PORTAL = "https://portal.example.test"


@override_settings(PUBLIC_FRONTEND_URL=PORTAL + "/")
class ApprovalUrlBuilderTests(TestCase):
    """A trailing slash on PUBLIC_FRONTEND_URL never produces '//' in a link."""

    def test_repair_approval_url(self):
        self.assertEqual(build_approval_url("tok123"), f"{PORTAL}/repair-approval/tok123")

    def test_repair_order_approval_url(self):
        self.assertEqual(build_order_approval_url("tok123"), f"{PORTAL}/repair-order-approval/tok123")

    def test_lead_approval_url(self):
        self.assertEqual(build_lead_approval_url("tok123"), f"{PORTAL}/lead-approval/tok123")

    def test_rental_approval_url(self):
        self.assertEqual(build_rental_approval_url("tok123"), f"{PORTAL}/rental-approval/tok123")

    def test_staff_set_password_url_keeps_uid_and_token(self):
        user = get_user_model().objects.create_user(username="url-staff", password="x-safe-pass-123")
        link = setup_link(user)
        prefix = f"{PORTAL}/set-password/"
        self.assertTrue(link.startswith(prefix), link)
        uid, token = link[len(prefix):].split("/")
        self.assertTrue(uid and token)
        self.assertTrue(setup_tokens.check_token(user, token))


@override_settings(PUBLIC_FRONTEND_URL=PORTAL)
class RepairApprovalLinkTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="url-admin", password="x-safe-pass", is_superuser=True)
        self.party = Party.objects.create(name="Url Customer", type=Party.RETAIL, phone="9876543210",
                                          email="cust@example.test", joined=date.today())
        store = StockPoint.objects.create(slug="url-shop", name="Url Shop", kind=StockPoint.SHOP)
        self.service = Service.objects.create(slug="url-diag", label="Diagnosis", segment=Service.SOFTWARE, charge=500)
        self.ticket = RepairTicket.objects.create(
            code="RPR-URL-1", party=self.party, brand="Dell", model_name="L5", stock_point=store,
            issue="No power", status=RepairTicket.DIAGNOSING, received=date.today(),
        )
        finalize_estimate(self.ticket, self.user, [{"service": self.service, "description": "Diagnosis",
                                                    "quantity": 1, "unit_price": 500}])

    def test_issued_link_message_and_wa_me_use_the_portal(self):
        approval, url, wa_url = issue_approval_link(self.ticket, self.user)
        token = url.rsplit("/", 1)[-1]
        self.assertTrue(url.startswith(f"{PORTAL}/repair-approval/"), url)
        # only the hash is stored; the 24-hour expiry is unchanged
        self.assertEqual(approval.token_hash, approval_token_hash(token))
        self.assertEqual(approval.status, RepairApproval.PENDING)
        self.assertAlmostEqual((approval.expires_at - timezone.now()).total_seconds(), 24 * 3600, delta=120)
        body = Message.objects.filter(party=self.party, channel=Message.WHATSAPP).latest("id").body
        self.assertIn(url, body)
        self.assertIn("portal.example.test", wa_url)

    def test_whatsapp_api_send_uses_the_portal(self):
        _, url, _ = issue_approval_link(self.ticket, self.user)
        with mock.patch("repairs.services.send_whatsapp", return_value={"status": "sent"}) as send:
            send_approval_link_whatsapp(self.ticket, url, self.user)
        self.assertIn(f"{PORTAL}/repair-approval/", send.call_args.args[1])

    def test_customer_emails_carry_the_portal_link(self):
        issue_approval_link(self.ticket, self.user)
        for message in mail.outbox:
            if "/repair-approval/" in message.body:
                self.assertIn(f"{PORTAL}/repair-approval/", message.body)

    def test_public_api_get_approve_and_repeat(self):
        _, url, _ = issue_approval_link(self.ticket, self.user)
        endpoint = f"/api/public/repair-approvals/{url.rsplit('/', 1)[-1]}/"
        public = APIClient()
        self.assertEqual(public.get(endpoint).status_code, 200)
        r = public.post(endpoint, {"decision": "approve", "consent": True}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "approved"), r.content)
        self.assertEqual(public.post(endpoint, {"decision": "approve", "consent": True}, format="json").status_code, 200)
        self.assertEqual(public.post(endpoint, {"decision": "reject"}, format="json").status_code, 409)
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.current_estimate.is_approved)

    def test_public_api_reject(self):
        _, url, _ = issue_approval_link(self.ticket, self.user)
        endpoint = f"/api/public/repair-approvals/{url.rsplit('/', 1)[-1]}/"
        r = APIClient().post(endpoint, {"decision": "reject", "reason": "Too costly"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "rejected"), r.content)
        self.assertEqual(RepairApproval.objects.get(token_hash=approval_token_hash(url.rsplit("/", 1)[-1])).status,
                         RepairApproval.REJECTED)

    def test_expired_link_is_gone(self):
        approval, url, _ = issue_approval_link(self.ticket, self.user)
        RepairApproval.objects.filter(pk=approval.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        endpoint = f"/api/public/repair-approvals/{url.rsplit('/', 1)[-1]}/"
        self.assertEqual(APIClient().get(endpoint).status_code, 410)


@override_settings(PUBLIC_FRONTEND_URL=PORTAL)
class LeadApprovalLinkTests(LeadBase):
    def issue(self):
        pk = self.new_lead()["id"]
        self.t.post(f"/api/leads/{pk}/check_in/", {}, format="json")
        self.t.post(f"/api/leads/{pk}/diagnose/", {"diagnosis": "board dead"}, format="json")
        self.t.post(f"/api/leads/{pk}/quote/", {"lines": self.lines()}, format="json")
        r = self.t.post(f"/api/leads/{pk}/send_link/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return pk, r.json()["approval_url"]

    def test_crm_generates_portal_lead_approval_url(self):
        _, url = self.issue()
        self.assertTrue(url.startswith(f"{PORTAL}/lead-approval/"), url)

    def test_status_column_fits_changes_requested(self):
        field = LeadApproval._meta.get_field("status")
        self.assertGreaterEqual(field.max_length, len(LeadApproval.CHANGES_REQUESTED))
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT character_maximum_length FROM information_schema.columns "
                               "WHERE table_name = 'leads_leadapproval' AND column_name = 'status'")
                self.assertGreaterEqual(cursor.fetchone()[0], len("changes_requested"))

    def test_ask_for_changes_is_saved_and_reported(self):
        pk, url = self.issue()
        endpoint = f"/api/public/lead-approvals/{url.rsplit('/', 1)[-1]}/"
        public = APIClient()
        r = public.post(endpoint, {"decision": "request_changes", "reason": "Skip the SSD"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "changes_requested"), r.content)
        approval = LeadApproval.objects.get(lead_id=pk, status=LeadApproval.CHANGES_REQUESTED)
        self.assertEqual((approval.reason, approval.source), ("Skip the SSD", LeadApproval.CUSTOMER))
        self.assertEqual(Lead.objects.get(pk=pk).status, Lead.DIAGNOSED)
        # the same decision again is idempotent; a different one conflicts
        self.assertEqual(public.post(endpoint, {"decision": "request_changes", "reason": "Skip the SSD"}, format="json").status_code, 200)
        self.assertEqual(public.post(endpoint, {"decision": "approve", "consent": True}, format="json").status_code, 409)
        self.assertEqual(public.get(endpoint).json()["status"], "changes_requested")

    def test_decline(self):
        pk, url = self.issue()
        endpoint = f"/api/public/lead-approvals/{url.rsplit('/', 1)[-1]}/"
        r = APIClient().post(endpoint, {"decision": "reject", "reason": "Too costly"}, format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "rejected"), r.content)
        self.assertEqual(Lead.objects.get(pk=pk).status, Lead.REJECTED)


@override_settings(PUBLIC_FRONTEND_URL=PORTAL)
class StaffPasswordResetLinkTests(TestCase):
    NEW_PASSWORD = "Quiet-Harbour-2048"

    def setUp(self):
        cache.clear()  # LoginRateThrottle counts password-setup calls per IP
        self.owner = client_for(make_user("url-owner", superuser=True))
        self.staff = make_user("url-staff-2", ["invoices.view"])
        self.staff.set_password("safe-test-password")
        self.staff.save()

    def reset_link(self):
        r = self.owner.post(f"/api/users/{self.staff.id}/reset-password/", {"delivery": "link"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["setup_url"]

    def endpoint(self, link):
        uid, token = link[len(f"{PORTAL}/set-password/"):].split("/")
        return f"/api/auth/password-setup/{uid}/{token}/"

    def test_admin_link_points_at_portal_with_uid_and_token(self):
        link = self.reset_link()
        self.assertRegex(link, rf"^{PORTAL}/set-password/[^/]+/[^/]+$")

    def test_weak_and_mismatched_passwords_are_refused(self):
        url = self.endpoint(self.reset_link())
        public = APIClient()
        weak = public.post(url, {"new_password": "short", "confirm_password": "short"}, format="json")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("new_password", weak.json())
        mismatch = public.post(url, {"new_password": self.NEW_PASSWORD, "confirm_password": self.NEW_PASSWORD + "x"}, format="json")
        self.assertEqual(mismatch.status_code, 400)
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.has_usable_password())

    def test_successful_reset_is_single_use_and_signs_in(self):
        url = self.endpoint(self.reset_link())
        public = APIClient()
        self.assertEqual(public.get(url).json()["valid"], True)
        ok = public.post(url, {"new_password": self.NEW_PASSWORD, "confirm_password": self.NEW_PASSWORD}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        # single use
        self.assertEqual(public.get(url).status_code, 400)
        login = APIClient().post("/api/auth/token/", {"username": self.staff.username, "password": self.NEW_PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200, login.content)
        self.assertIn("access", login.json())

    def test_invalid_and_expired_tokens_are_refused(self):
        url = self.endpoint(self.reset_link())
        self.assertEqual(APIClient().get(url.rstrip("/") + "x/").status_code, 400)
        later = setup_tokens._now() + timedelta(hours=SETUP_LINK_HOURS, minutes=5)
        with mock.patch.object(setup_tokens, "_now", return_value=later):
            self.assertEqual(APIClient().get(url).status_code, 400)
