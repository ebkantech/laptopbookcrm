import importlib
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.apps import apps as django_apps
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from crmbook_backend.testing import client_for, make_user
from parties.models import Message, Party
from rentals.models import Rental, add_months
from .access import rental_end_at
from .models import PortalAccessLog, PortalInvite
from .services import create_portal_invite

ROOMY_RATES = {"otp_verify": "1000/min", "otp_resend": "1000/hour", "otp_resend_invite": "1000/hour", "portal_pdf": "1000/hour"}
FIXED_NOW = datetime(2026, 10, 11, 9, 30, tzinfo=dt_timezone.utc)
TEST_OTP_KEY = "5FHcEUaf1NnMvbwl0jlOd_2aEUMaX0p9R6fmaXZ1Ni4="  # test-only Fernet key


def code_from_last_email():
    return re.search(r"code is (\d{6})", mail.outbox[-1].body).group(1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", PORTAL_OTP_ENCRYPTION_KEY=TEST_OTP_KEY)
class PortalTestBase(TestCase):
    def setUp(self):
        cache.clear()
        rates = mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", dict(ROOMY_RATES))
        rates.start()
        self.addCleanup(rates.stop)
        self.client = APIClient()
        self.party = Party.objects.create(
            name="Portal Customer", type=Party.RENTAL, phone="9876543210",
            email="customer@example.test", joined=date.today(),
        )
        self.rental = self.make_rental(self.party)

    def make_rental(self, party, start=None, tenure=6, status=Rental.ACTIVE):
        start = start or date.today() - timedelta(days=10)
        return Rental.objects.create(
            party=party, product_label="Dell Latitude", monthly_fee=1500, start=start,
            tenure_months=tenure, last_payment=start, status=status,
        )

    def make_party(self, kind, email="buyer@example.test"):
        return Party.objects.create(name=f"{kind} buyer", type=kind, phone="9000000000", email=email, joined=date.today())

    def issue(self, party=None):
        invite, _ = create_portal_invite(party or self.party, None)
        return invite, code_from_last_email()

    def status(self, invite):
        return self.client.get(f"/api/portal/invite-status/{invite.token}/")

    def verify(self, invite, otp):
        return self.client.post("/api/portal/verify/", {"token": str(invite.token), "otp": otp}, format="json")

    def resend(self, invite):
        return self.client.post("/api/portal/resend-otp/", {"token": str(invite.token)}, format="json")

    def skip_cooldown(self, invite):
        PortalInvite.objects.filter(pk=invite.pk).update(otp_issued_at=timezone.now() - timedelta(minutes=5))

    def wrong(self, otp):
        return "000000" if otp != "000000" else "111111"

    def me(self, portal_token):
        return APIClient().get("/api/portal/me/", HTTP_AUTHORIZATION=f"Portal {portal_token}")


class ReusableLinkTests(PortalTestBase):
    def test_link_survives_login_and_issues_fresh_codes_until_expiry(self):
        invite, otp = self.issue()
        expires_at = invite.expires_at
        first = self.status(invite)
        self.assertEqual(first.status_code, 200)
        self.assertEqual((first.json()["status"], first.json()["otp_status"]), ("active", "active"))

        login = self.verify(invite, otp)
        self.assertEqual(login.status_code, 200, login.content)
        self.assertEqual(set(login.json()), {"portal_token", "party", "access_log_id"})
        invite.refresh_from_db()
        self.assertIsNone(invite.revoked_at)
        self.assertIsNone(invite.consumed_at)
        self.assertIsNotNone(invite.last_verified_at)
        self.assertEqual(invite.otp_digest, "")  # the code is spent

        reopened = self.status(invite)
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.json()["otp_status"], "none")
        self.assertIsNone(reopened.json()["otp_expires_in"])

        reused = self.verify(invite, otp)
        self.assertEqual((reused.status_code, reused.json()["code"]), (400, "otp_invalid"))

        self.skip_cooldown(invite)
        fresh = self.resend(invite)
        self.assertEqual(fresh.status_code, 200, fresh.content)
        new_otp = code_from_last_email()
        self.assertEqual(self.verify(invite, new_otp).status_code, 200)
        self.assertEqual(self.verify(invite, new_otp).json()["code"], "otp_invalid")
        invite.refresh_from_db()
        self.assertEqual(invite.expires_at, expires_at)
        self.assertEqual(PortalAccessLog.objects.filter(party=self.party).count(), 2)

    def test_replaced_and_revoked_links_stay_closed(self):
        first, first_otp = self.issue()
        second, _ = self.issue()
        for call in (self.status(first), self.verify(first, first_otp), self.resend(first)):
            self.assertEqual((call.status_code, call.json()["code"]), (410, "invite_revoked"))
        self.assertEqual(self.status(second).status_code, 200)

        staff = client_for(make_user("portal-staff", ["parties.view", "parties.manage"]))
        self.assertEqual(staff.post(f"/api/parties/{self.party.id}/revoke-portal-access/").status_code, 200)
        self.assertEqual(self.status(second).json()["code"], "invite_revoked")

    def test_expired_link_cannot_be_used_or_revived_by_resend(self):
        invite, otp = self.issue()
        past = timezone.now() - timedelta(seconds=1)
        PortalInvite.objects.filter(pk=invite.pk).update(expires_at=past)
        for call in (self.status(invite), self.verify(invite, otp), self.resend(invite)):
            self.assertEqual((call.status_code, call.json()["code"]), (410, "invite_expired"))
        invite.refresh_from_db()
        self.assertEqual(invite.expires_at, past)
        self.assertTrue(invite.check_otp(otp))  # resend did not touch the code either

    def test_unknown_and_malformed_tokens(self):
        unknown = self.client.post("/api/portal/resend-otp/", {"token": "3f2504e0-4f89-11d3-9a0c-0305e82c3301"}, format="json")
        self.assertEqual((unknown.status_code, unknown.json()["code"]), (404, "invite_invalid"))
        for path in ("/api/portal/resend-otp/", "/api/portal/verify/"):
            bad = self.client.post(path, {"token": "not-a-token", "otp": "123456"}, format="json")
            self.assertEqual((bad.status_code, bad.json()["code"]), (400, "invalid_request"))
        invite, _ = self.issue()
        self.assertEqual(self.verify(invite, "12ab").json()["code"], "invalid_request")


class InviteExpiryTests(PortalTestBase):
    def test_rental_link_lasts_until_tenure_end(self):
        invite, _ = self.issue()
        end_date = add_months(self.rental.start, self.rental.tenure_months)
        self.assertEqual(invite.expires_at, datetime(end_date.year, end_date.month, end_date.day, tzinfo=dt_timezone.utc))
        self.assertEqual(invite.expires_at, rental_end_at(self.rental))

    def test_dealer_and_retail_links_last_24_hours(self):
        for kind in (Party.DEALER, Party.RETAIL):
            with mock.patch("django.utils.timezone.now", return_value=FIXED_NOW):
                invite, _ = self.issue(self.make_party(kind))
            self.assertEqual(invite.expires_at, FIXED_NOW + timedelta(hours=24))
            self.assertEqual(invite.otp_expires_at, FIXED_NOW + timedelta(minutes=30))

    def test_rental_without_running_agreement_is_refused(self):
        other = self.make_party(Party.RENTAL)
        for status in (Rental.DRAFT, Rental.PENDING_APPROVAL, Rental.REJECTED, Rental.CANCELLED, Rental.CLOSED):
            self.make_rental(other, status=status)
        self.make_rental(other, start=date.today() - timedelta(days=400), tenure=6)  # active, but tenure over
        with self.assertRaises(ValidationError):
            create_portal_invite(other, None)
        self.assertFalse(PortalInvite.objects.filter(party=other).exists())

    def test_latest_qualifying_agreement_wins(self):
        later = self.make_rental(self.party, tenure=18, status=Rental.APPROVED)
        self.make_rental(self.party, tenure=48, status=Rental.CLOSED)  # never extends access
        invite, _ = self.issue()
        self.assertEqual(invite.expires_at, rental_end_at(later))

    def test_rental_closed_early_closes_the_link(self):
        invite, otp = self.issue()
        Rental.objects.filter(pk=self.rental.pk).update(status=Rental.CLOSED)
        self.assertEqual(self.verify(invite, otp).json()["code"], "invite_expired")


class OtpSecurityTests(PortalTestBase):
    def test_otp_expires_after_30_minutes_but_link_stays_usable(self):
        with mock.patch("django.utils.timezone.now", return_value=FIXED_NOW):
            invite, otp = self.issue(self.make_party(Party.DEALER))
        self.assertNotEqual(invite.otp_digest, otp)
        with mock.patch("django.utils.timezone.now", return_value=FIXED_NOW + timedelta(minutes=30, seconds=1)):
            status = self.status(invite).json()
            self.assertEqual((status["otp_status"], status["otp_expires_in"]), ("expired", 0))
            late = self.verify(invite, otp)
            self.assertEqual((late.status_code, late.json()["code"]), (400, "otp_expired"))
            fresh = self.resend(invite)
            self.assertEqual(fresh.status_code, 200, fresh.content)
            self.assertEqual(fresh.json()["otp_expires_in"], 1800)
            self.assertEqual(self.verify(invite, code_from_last_email()).status_code, 200)

    def test_code_still_works_just_before_30_minutes(self):
        with mock.patch("django.utils.timezone.now", return_value=FIXED_NOW):
            invite, otp = self.issue(self.make_party(Party.RETAIL))
        with mock.patch("django.utils.timezone.now", return_value=FIXED_NOW + timedelta(minutes=29, seconds=59)):
            self.assertEqual(self.verify(invite, otp).status_code, 200)

    def test_resend_invalidates_previous_code_and_keeps_link_expiry(self):
        invite, old = self.issue()
        expires_at = invite.expires_at
        self.skip_cooldown(invite)
        response = self.resend(invite)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["masked_email"], "c***@e***")
        self.assertEqual(body["resend_available_in"], 60)
        self.assertNotIn("customer@example.test", str(body))
        self.assertFalse({"otp", "otp_digest", "code_value"} & set(body))
        new = code_from_last_email()
        if new != old:
            self.assertEqual(self.verify(invite, old).json()["code"], "otp_invalid")
        self.assertEqual(self.verify(invite, new).status_code, 200)
        invite.refresh_from_db()
        self.assertEqual(invite.expires_at, expires_at)
        recorded = Message.objects.filter(party=self.party, channel=Message.EMAIL).order_by("-id").first()
        self.assertNotIn(new, recorded.body)
        self.assertIn("OTP Resent by Customer", recorded.body)
        self.assertIn("delivery: sent", recorded.body)

    def test_five_failures_lock_the_code_until_a_new_one_is_sent(self):
        invite, otp = self.issue()
        for remaining in (4, 3, 2, 1):
            response = self.verify(invite, self.wrong(otp))
            self.assertEqual((response.status_code, response.json()["attempts_remaining"]), (400, remaining))
        locked = self.verify(invite, self.wrong(otp))
        self.assertEqual((locked.json()["code"], locked.json()["attempts_remaining"]), ("otp_attempts_exceeded", 0))
        self.assertEqual(self.verify(invite, otp).json()["code"], "otp_attempts_exceeded")
        self.assertEqual(self.status(invite).status_code, 200)  # the link itself is fine

        self.skip_cooldown(invite)
        self.assertEqual(self.resend(invite).status_code, 200)
        invite.refresh_from_db()
        self.assertEqual(invite.failed_attempts, 0)
        self.assertEqual(self.verify(invite, code_from_last_email()).status_code, 200)

    def test_code_changed_mid_verification_cannot_log_in(self):
        """A resend or a parallel verify that lands while this request is
        checking the hash must win: the compare-and-swap rejects the stale code."""
        invite, otp = self.issue()
        real_check = PortalInvite.check_otp

        def racing_check(instance, code):
            result = real_check(instance, code)
            PortalInvite.objects.filter(pk=instance.pk).update(otp_digest="")  # the other request's commit
            return result

        with mock.patch.object(PortalInvite, "check_otp", racing_check):
            response = self.verify(invite, otp)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "otp_invalid"))
        self.assertNotIn("portal_token", response.json())
        self.assertFalse(PortalAccessLog.objects.filter(party=self.party).exists())

    def test_resend_cooldown_returns_retry_after(self):
        invite, _ = self.issue()
        self.assertEqual(self.status(invite).json()["resend_available_in"], 60)
        response = self.resend(invite)
        self.assertEqual((response.status_code, response.json()["code"]), (429, "resend_throttled"))
        self.assertTrue(0 < int(response["Retry-After"]) <= 60)
        self.assertEqual(response.json()["resend_available_in"], int(response["Retry-After"]))

    @override_settings(PORTAL_OTP_RESEND_COOLDOWN_SECONDS=0)
    def test_per_link_and_per_ip_resend_limits(self):
        invite, _ = self.issue()
        with mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", {**ROOMY_RATES, "otp_resend_invite": "2/hour"}):
            self.assertEqual(self.resend(invite).status_code, 200)
            self.assertEqual(self.resend(invite).status_code, 200)
            limited = self.resend(invite)
        self.assertEqual((limited.status_code, limited.json()["code"]), (429, "resend_throttled"))
        self.assertIn("Retry-After", limited)

        cache.clear()
        with mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", {**ROOMY_RATES, "otp_resend": "1/hour"}):
            self.assertEqual(self.resend(invite).status_code, 200)
            limited = self.resend(invite)
        self.assertEqual((limited.status_code, limited.json()["code"]), (429, "resend_throttled"))

    def test_failed_resend_email_keeps_the_current_code_and_reports_failure(self):
        invite, old = self.issue()
        self.skip_cooldown(invite)
        before = PortalInvite.objects.get(pk=invite.pk)
        with mock.patch("portal.services.send_email", return_value={"status": "failed"}) as send:
            response = self.resend(invite)
        self.assertEqual((response.status_code, response.json()["code"]), (503, "email_delivery_failed"))
        self.assertNotIn("masked_email", response.json())
        attempted = re.search(r"code is (\d{6})", send.call_args.args[2]).group(1)
        invite.refresh_from_db()
        self.assertEqual((invite.otp_digest, invite.otp_issued_at, invite.otp_expires_at),
                         (before.otp_digest, before.otp_issued_at, before.otp_expires_at))
        if attempted != old:
            self.assertEqual(self.verify(invite, attempted).json()["code"], "otp_invalid")  # undelivered code never valid
        failed = Message.objects.filter(party=self.party, channel=Message.EMAIL).order_by("-id").first()
        self.assertIn("delivery: failed", failed.body)
        self.assertNotIn(attempted, failed.body)
        self.assertEqual(self.verify(invite, old).status_code, 200)  # the delivered code still works

    def test_resend_without_email_on_file(self):
        invite, _ = self.issue()
        Party.objects.filter(pk=self.party.pk).update(email="")
        self.skip_cooldown(invite)
        self.assertEqual(self.resend(invite).json()["code"], "no_email_on_file")


class InviteAuthorizationTests(PortalTestBase):
    def test_portal_manage_staff_can_invite_dealer_and_retail(self):
        staff = client_for(make_user("portal-manager", ["portal.manage"]))
        for kind in (Party.DEALER, Party.RETAIL):
            party = self.make_party(kind)
            with mock.patch("portal.services.send_whatsapp", return_value={}) as whatsapp:
                response = staff.post("/api/portal-invites/", {"party": party.id}, format="json")
            self.assertEqual(response.status_code, 201, response.content)
            invite = PortalInvite.objects.get(party=party)
            self.assertAlmostEqual((invite.expires_at - invite.created_at).total_seconds(), 86400, delta=5)
            wa = Message.objects.get(party=party, channel=Message.WHATSAPP).body
            self.assertIn(str(invite.token), wa)
            self.assertIn("30 minutes", wa)
            self.assertNotIn("link expires in 30 minutes", wa)
            whatsapp.assert_called_once()

    def test_rental_without_agreement_is_400_through_the_api(self):
        staff = client_for(make_user("portal-manager", ["portal.manage"]))
        party = self.make_party(Party.RENTAL)
        response = staff.post("/api/portal-invites/", {"party": party.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_staff_without_permission_and_portal_customers_cannot_invite(self):
        other_staff = client_for(make_user("no-portal", ["parties.view"]))
        self.assertEqual(other_staff.post("/api/portal-invites/", {"party": self.party.id}, format="json").status_code, 403)
        self.assertEqual(other_staff.post(f"/api/parties/{self.party.id}/portal-invite/").status_code, 403)

        invite, otp = self.issue()
        portal_token = self.verify(invite, otp).json()["portal_token"]
        customer = APIClient()
        customer.credentials(HTTP_AUTHORIZATION=f"Portal {portal_token}")
        self.assertIn(customer.post("/api/portal-invites/", {"party": self.party.id}, format="json").status_code, (401, 403))
        self.assertIn(customer.post(f"/api/parties/{self.party.id}/portal-invite/").status_code, (401, 403))
        self.assertEqual(PortalInvite.objects.filter(party=self.party).count(), 1)

    def test_invite_creation_limit_is_kept(self):
        for _ in range(3):
            self.issue()
        with self.assertRaises(ValidationError):
            create_portal_invite(self.party, None)
        staff = client_for(make_user("portal-manager", ["portal.manage"]))
        self.assertEqual(staff.post("/api/portal-invites/", {"party": self.party.id}, format="json").status_code, 429)


class PortalSessionTests(PortalTestBase):
    def login(self, party=None):
        invite, otp = self.issue(party)
        return invite, self.verify(invite, otp).json()["portal_token"]

    def test_private_endpoints_require_an_otp_session(self):
        self.assertEqual(self.client.get("/api/portal/me/").status_code, 403)
        _, token = self.login()
        self.assertEqual(self.me(token).status_code, 200)

    def test_rental_session_ends_with_the_tenure(self):
        _, token = self.login()
        end = rental_end_at(self.rental)
        with mock.patch("django.utils.timezone.now", return_value=end - timedelta(seconds=1)):
            self.assertEqual(self.me(token).status_code, 200)
        with mock.patch("django.utils.timezone.now", return_value=end):
            self.assertEqual(self.me(token).status_code, 403)

    def test_rental_session_ends_when_agreement_is_closed(self):
        _, token = self.login()
        Rental.objects.filter(pk=self.rental.pk).update(status=Rental.CLOSED)
        self.assertEqual(self.me(token).status_code, 403)

    def test_dealer_and_retail_sessions_outlive_the_24h_link(self):
        for kind in (Party.DEALER, Party.RETAIL):
            invite, token = self.login(self.make_party(kind))
            PortalInvite.objects.filter(pk=invite.pk).update(expires_at=timezone.now() - timedelta(hours=1))
            with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=3)):
                self.assertEqual(self.me(token).status_code, 200)

    def test_revoked_session_and_link_stay_invalid(self):
        invite, token = self.login()
        staff = client_for(make_user("portal-staff", ["parties.view", "parties.manage"]))
        self.assertEqual(staff.post(f"/api/parties/{self.party.id}/revoke-portal-access/").status_code, 200)
        self.assertEqual(self.me(token).status_code, 403)
        self.assertEqual(self.status(invite).status_code, 410)

    def test_status_response_never_leaks_identity_or_secrets(self):
        invite, _ = self.issue()
        body = self.status(invite).json()
        self.assertNotIn("customer@example.test", str(body))
        self.assertNotIn(invite.otp_digest, str(body))
        self.assertTrue({"masked_email", "expires_at", "invite_expires_at", "otp_expires_at", "otp_expires_in",
                         "server_time", "resend_available_in"} <= set(body))


class LegacyInviteMigrationTests(TestCase):
    def test_used_or_replaced_legacy_links_stay_closed(self):
        party = Party.objects.create(name="Legacy", type=Party.RETAIL, phone="9000000000", email="l@x.example", joined=date.today())
        created = timezone.now() - timedelta(minutes=10)
        used = PortalInvite.objects.create(party=party, expires_at=created + timedelta(minutes=30), consumed_at=created)
        open_one = PortalInvite.objects.create(party=party, expires_at=created + timedelta(minutes=30))
        open_one.set_otp("123456")
        open_one.save()
        PortalInvite.objects.filter(pk__in=[used.pk, open_one.pk]).update(created_at=created)

        migration = importlib.import_module("portal.migrations.0005_reusable_invite_links_and_otp_expiry")
        migration.carry_over_legacy_state(django_apps, None)

        used.refresh_from_db()
        open_one.refresh_from_db()
        self.assertEqual((used.revoked_at, used.revoked_reason), (created, PortalInvite.LEGACY_CONSUMED))
        self.assertFalse(used.is_valid)
        self.assertIsNone(open_one.revoked_at)
        self.assertEqual(open_one.otp_expires_at, open_one.expires_at)  # never extended
        self.assertEqual(open_one.otp_issued_at, created)


class PortalCorsTests(PortalTestBase):
    @override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:3000"])
    def test_portal_can_read_retry_after_cross_origin(self):
        invite, _ = self.issue()
        response = self.client.post(
            "/api/portal/resend-otp/", {"token": str(invite.token)}, format="json", HTTP_ORIGIN="http://localhost:3000",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:3000")
        self.assertIn("retry-after", response["Access-Control-Expose-Headers"].lower())
