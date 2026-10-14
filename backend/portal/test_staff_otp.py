"""
Per-code CRM history: one email-history entry per issued code, each code
kept encrypted and readable by portal.manage staff for good, with a
status -- while authentication stays strictly on the current hashed code.
"""
import re
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from crmbook_backend.testing import client_for, make_user
from parties.models import Message, Party
from rentals.models import Rental
from . import otp_vault
from .models import PortalInvite, PortalOtpAccessLog, PortalOtpIssue
from .tests import PortalTestBase, code_from_last_email

OTP_RE = re.compile(r"^\d{6}$")


class StaffOtpTestBase(PortalTestBase):
    def setUp(self):
        super().setUp()
        self.portal_staff = client_for(make_user("portal-admin", ["parties.view", "parties.manage", "portal.manage"]))
        self.plain_staff = client_for(make_user("party-clerk", ["parties.view", "parties.manage"]))

    def invite_via_crm(self, party=None, client=None):
        party = party or self.party
        response = (client or self.portal_staff).post(f"/api/parties/{party.id}/portal-invite/")
        self.assertEqual(response.status_code, 201, response.content)
        return response, PortalInvite.objects.filter(party=party).order_by("-created_at").first(), code_from_last_email()

    def history(self, party=None, client=None):
        return (client or self.portal_staff).get(f"/api/parties/{(party or self.party).id}/portal-otps/")

    def rows(self, party=None):
        response = self.history(party)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["otps"]

    def current(self, party=None, client=None):
        return (client or self.portal_staff).get(f"/api/parties/{(party or self.party).id}/portal-otp/")

    def resend_ok(self, invite):
        self.skip_cooldown(invite)
        response = self.resend(invite)
        self.assertEqual(response.status_code, 200, response.content)
        return code_from_last_email()

    def email_entries(self, party=None):
        return list(Message.objects.filter(party=party or self.party, channel=Message.EMAIL).order_by("id"))


class HistoryEntryTests(StaffOtpTestBase):
    def test_invitation_creates_an_entry_with_its_code(self):
        response, invite, code = self.invite_via_crm()
        [entry] = self.email_entries()
        self.assertTrue(entry.body.startswith(f"Portal Invitation Generated · Invitation #{invite.pk} · Code 1"))
        self.assertIn("code is ******", entry.body)  # storage stays masked; the CRM fills in the digits
        self.assertNotIn(code, entry.body)
        self.assertEqual((response.json()["otp"], response.json()["otp_message_id"]), (code, entry.id))
        [row] = self.rows()
        self.assertEqual((row["message_id"], row["otp"], row["status"], row["sequence"], row["label"]),
                         (entry.id, code, "active", 1, "Portal Invitation Generated"))

    def test_every_resend_adds_a_new_entry_and_earlier_ones_never_change(self):
        _, invite, first = self.invite_via_crm()
        [original] = self.email_entries()
        second = self.resend_ok(invite)
        after_first_resend = self.email_entries()
        self.assertEqual(len(after_first_resend), 2)
        self.assertTrue(after_first_resend[1].body.startswith(f"OTP Resent by Customer · Invitation #{invite.pk} · Code 2"))
        third = self.resend_ok(invite)
        entries = self.email_entries()
        self.assertEqual(len(entries), 3)
        self.assertTrue(entries[2].body.startswith(f"OTP Resent by Customer · Invitation #{invite.pk} · Code 3"))
        # earlier entries are untouched records
        self.assertEqual((entries[0].body, entries[0].edited_at), (original.body, None))
        self.assertEqual((entries[1].body, entries[1].edited_at), (after_first_resend[1].body, None))
        for entry in entries:
            for code in (first, second, third):
                self.assertNotIn(code, entry.body)

        rows = self.rows()
        self.assertEqual([r["message_id"] for r in rows], [e.id for e in entries])
        self.assertEqual([r["otp"] for r in rows], [first, second, third])
        self.assertEqual([r["status"] for r in rows], ["superseded", "superseded", "active"])
        self.assertEqual([r["kind"] for r in rows], ["invitation", "resend", "resend"])
        self.assertEqual(self.current().json()["otp_message_id"], entries[2].id)

    def test_resent_codes_invalidate_earlier_ones_for_login_only(self):
        _, invite, first = self.invite_via_crm()
        second = self.resend_ok(invite)
        if second != first:
            self.assertEqual(self.verify(invite, first).json()["code"], "otp_invalid")
        self.assertEqual(self.rows()[0]["otp"], first)  # still readable in its entry
        self.assertEqual(self.verify(invite, second).status_code, 200)

    def test_failed_resend_adds_no_successful_resend_entry(self):
        _, invite, first = self.invite_via_crm()
        self.skip_cooldown(invite)
        with mock.patch("portal.services.send_email", return_value={"status": "failed"}) as send:
            self.assertEqual(self.resend(invite).status_code, 503)
        attempted = re.search(r"code is (\d{6})", send.call_args.args[2]).group(1)
        entries = self.email_entries()
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[1].body.startswith(f"OTP Resend Failed · Invitation #{invite.pk}"))
        self.assertIn("delivery: failed", entries[1].body)
        self.assertIn("No new verification code was issued", entries[1].body)
        self.assertNotIn(attempted, entries[1].body)
        self.assertNotIn("OTP Resent by Customer", entries[1].body)
        rows = self.rows()
        self.assertEqual([(r["otp"], r["status"]) for r in rows], [(first, "active")])  # no row for the failed code
        self.assertEqual(self.verify(invite, first).status_code, 200)


class HistoricalVisibilityTests(StaffOtpTestBase):
    def test_used_code_stays_visible_but_cannot_sign_in_again(self):
        _, invite, code = self.invite_via_crm()
        self.assertEqual(self.verify(invite, code).status_code, 200)
        [row] = self.rows()
        self.assertEqual((row["otp"], row["status"]), (code, "used"))
        self.assertEqual(self.verify(invite, code).json()["code"], "otp_invalid")
        self.rows()  # reading history again changes nothing
        self.assertEqual(self.verify(invite, code).json()["code"], "otp_invalid")

    def test_expired_code_stays_visible_but_cannot_sign_in(self):
        _, invite, code = self.invite_via_crm()
        with mock.patch("django.utils.timezone.now", return_value=invite.otp_expires_at):
            [row] = self.rows()
            self.assertEqual((row["otp"], row["status"]), (code, "expired"))
            self.assertEqual(self.verify(invite, code).json()["code"], "otp_expired")
        self.assertEqual(self.current().status_code, 200)  # sanity: before expiry it was the active one

    def test_locked_revoked_and_replaced_codes_keep_their_values(self):
        _, invite, code = self.invite_via_crm()
        for _ in range(5):
            self.verify(invite, self.wrong(code))
        self.assertEqual([(r["otp"], r["status"]) for r in self.rows()], [(code, "locked")])

        _, second_invite, second = self.invite_via_crm()  # replaces the first link
        self.assertEqual(self.portal_staff.post(f"/api/parties/{self.party.id}/revoke-portal-access/").status_code, 200)
        rows = self.rows()
        self.assertEqual([(r["otp"], r["status"], r["invite_id"]) for r in rows],
                         [(code, "locked", invite.pk), (second, "revoked", second_invite.pk)])
        self.assertEqual(self.verify(second_invite, second).json()["code"], "invite_revoked")
        self.assertEqual(self.current().status_code, 404)  # nothing is ACTIVE

    def test_link_expired_by_rental_end_marks_code_expired(self):
        _, _, code = self.invite_via_crm()
        Rental.objects.filter(pk=self.rental.pk).update(status=Rental.CLOSED)
        self.assertEqual([(r["otp"], r["status"]) for r in self.rows()], [(code, "expired")])

    def test_every_account_type(self):
        for kind in (Party.DEALER, Party.RETAIL):
            party = self.make_party(kind, email=f"{kind.lower()}@example.test")
            _, _, code = self.invite_via_crm(party)
            self.assertEqual([r["otp"] for r in self.rows(party)], [code])


class OtpDisclosureSecurityTests(StaffOtpTestBase):
    def test_only_portal_manage_staff_get_plaintext(self):
        response, _, code = self.invite_via_crm(client=self.plain_staff)
        self.assertNotIn("otp", response.json())
        for client in (self.plain_staff, client_for(make_user("viewer", ["parties.view"]))):
            self.assertEqual(self.history(client=client).status_code, 403)
            self.assertEqual(self.current(client=client).status_code, 403)
        self.assertEqual(self.history(client=APIClient()).status_code, 401)
        self.assertEqual(self.rows()[0]["otp"], code)

    def test_customer_facing_endpoints_never_expose_codes(self):
        _, invite, first = self.invite_via_crm()
        second = self.resend_ok(invite)
        token = self.verify(invite, second).json()["portal_token"]
        customer = APIClient()
        customer.credentials(HTTP_AUTHORIZATION=f"Portal {token}")
        self.assertIn(self.history(client=customer).status_code, (401, 403))
        exposed = [
            self.status(invite).content, customer.get("/api/portal/me/").content,
            customer.get("/api/portal/invoices/").content, customer.get("/api/portal/rentals/").content,
        ]
        for body in exposed:
            for code in (first, second):
                self.assertNotIn(code.encode(), body)

    def test_each_party_only_yields_its_own_codes(self):
        other = self.make_party(Party.RETAIL, email="other@example.test")
        _, _, mine = self.invite_via_crm()
        _, _, theirs = self.invite_via_crm(other)
        self.assertEqual([r["otp"] for r in self.rows()], [mine])
        self.assertEqual([r["otp"] for r in self.rows(other)], [theirs])

    def test_plaintext_reads_are_audited_without_the_code(self):
        _, _, code = self.invite_via_crm()
        PortalOtpAccessLog.objects.all().delete()
        self.rows()
        log = PortalOtpAccessLog.objects.get()
        self.assertEqual((log.party_id, log.codes_disclosed, log.path), (self.party.id, 1, f"/api/parties/{self.party.id}/portal-otps/"))
        self.assertIsNotNone(log.user_id)
        self.assertNotIn(code, str(log.__dict__))

    def test_codes_are_encrypted_and_bound_to_their_issue(self):
        _, invite, code = self.invite_via_crm()
        second = self.resend_ok(invite)
        first_issue, second_issue = PortalOtpIssue.objects.filter(invite=invite).order_by("sequence")
        for issue, plain in ((first_issue, code), (second_issue, second)):
            self.assertNotIn(plain, issue.otp_ciphertext)
            self.assertNotIn(plain, invite.otp_digest)
            self.assertEqual(otp_vault.unseal(issue.otp_ciphertext, otp_vault.binding_for(issue)), plain)
        # a ciphertext moved onto another row, or tampered with, does not open
        self.assertIsNone(otp_vault.unseal(first_issue.otp_ciphertext, otp_vault.binding_for(second_issue)))
        self.assertIsNone(otp_vault.unseal(first_issue.otp_ciphertext[:-4] + "AAAA", otp_vault.binding_for(first_issue)))
        with override_settings(PORTAL_OTP_ENCRYPTION_KEY="dR2iH4oP8a0c5mX9yZ1qW3eR5tY7uI9oP1aS3dF5gH8="):
            self.assertIsNone(otp_vault.unseal(first_issue.otp_ciphertext, otp_vault.binding_for(first_issue)))

    @override_settings(PORTAL_OTP_ENCRYPTION_KEY="")
    def test_without_a_key_nothing_is_stored_or_shown(self):
        response, invite, _ = self.invite_via_crm()
        self.assertNotIn("otp", response.json())
        self.assertEqual(PortalOtpIssue.objects.get(invite=invite).otp_ciphertext, "")
        self.assertEqual((self.history().status_code, self.history().json()["code"]), (503, "otp_copy_disabled"))
