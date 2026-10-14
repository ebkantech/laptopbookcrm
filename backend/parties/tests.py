import os
import re
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings

from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Message, Party
from portal.models import PortalInvite
from rentals.models import Rental
from sales.models import Invoice


@mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"})
class PartyApiTests(TestCase):
    def setUp(self):
        self.manager = client_for(make_user("party-manager", ["parties.view", "parties.manage", "parties.edit"]))
        self.viewer = client_for(make_user("party-viewer", ["parties.view"]))
        self.rental = Party.objects.create(
            name="Rental Corp", type=Party.RENTAL, phone="9876543210", email="ops@rental.example", joined=date.today()
        )
        # a running agreement -- Rental portal invitations require one
        Rental.objects.create(
            party=self.rental, product_label="Dell Latitude", monthly_fee=1500, start=date.today(),
            tenure_months=6, last_payment=date.today(), status=Rental.ACTIVE,
        )
        self.shop = StockPoint.objects.create(slug="party-test-shop", name="Party Test Shop", kind=StockPoint.SHOP)

    def create_party(self, client, phone="9876501234"):
        return client.post("/api/parties/", {
            "name": "New Retail Customer", "type": Party.RETAIL, "phone": phone,
            "email": "customer@example.com", "city": "Delhi", "joined": date.today().isoformat(),
        }, format="json")

    def test_create_runs_whatsapp_check(self):
        good = self.create_party(self.manager)
        self.assertEqual(good.status_code, 201, good.content)
        self.assertTrue(Party.objects.get(id=good.json()["id"]).whatsapp_verified)

        bad = self.create_party(self.manager, phone="12345")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("phone", bad.json())

    def test_create_requires_contact_fields_and_valid_email(self):
        body = {"name": "Incomplete", "type": Party.RETAIL, "phone": "9876501234", "joined": date.today().isoformat()}
        missing = self.manager.post("/api/parties/", body, format="json")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("email", missing.json())
        self.assertIn("city", missing.json())

        body.update(email="not-an-email", city="Delhi")
        invalid = self.manager.post("/api/parties/", body, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("email", invalid.json())

    def test_phone_change_rechecks_whatsapp(self):
        response = self.manager.patch(f"/api/parties/{self.rental.id}/", {"phone": "9876543211"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.rental.refresh_from_db()
        self.assertTrue(self.rental.whatsapp_verified)

    def test_update_persists_trimmed_customer_fields(self):
        response = self.manager.patch(f"/api/parties/{self.rental.id}/", {"name": "  Rental Company  ", "city": "  Jaipur  "}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.rental.refresh_from_db()
        self.assertEqual((self.rental.name, self.rental.city), ("Rental Company", "Jaipur"))

    def test_customer_update_needs_edit_permission_not_just_manage(self):
        # Sales Staff hold parties.manage (create, message, portal) but not parties.edit
        sales = client_for(make_user("party-sales", ["parties.view", "parties.manage"]))
        for method in (sales.patch, sales.put):
            response = method(f"/api/parties/{self.rental.id}/", {"name": "Renamed"}, format="json")
            self.assertEqual(response.status_code, 403)
        self.rental.refresh_from_db()
        self.assertEqual(self.rental.name, "Rental Corp")
        created = sales.post("/api/parties/", {"name": "New", "type": Party.RETAIL, "phone": "9000000011",
                                               "email": "new@x.example", "city": "Delhi", "joined": date.today().isoformat()}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        with mock.patch("parties.views.send_email", return_value={"status": "sent"}):
            message = sales.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "email", "body": "Hi"}, format="json")
        self.assertEqual(message.status_code, 201)

    def test_search_by_name(self):
        Party.objects.create(name="Someone Else", type=Party.RETAIL, phone="9000000000", joined=date.today())
        names = [p["name"] for p in results(self.viewer.get("/api/parties/", {"q": "rental"}))]
        self.assertEqual(names, ["Rental Corp"])

    def test_viewer_cannot_write(self):
        self.assertEqual(self.create_party(self.viewer).status_code, 403)
        self.assertEqual(self.viewer.post(f"/api/parties/{self.rental.id}/message/", {"body": "hi"}, format="json").status_code, 403)
        self.assertEqual(client_for(make_user("no-parties")).get("/api/parties/").status_code, 403)

    def test_customer_with_invoice_cannot_be_deleted(self):
        invoice = Invoice.objects.create(code="INV-PARTY-DELETE", party=self.rental, stock_point=self.shop, date=date.today())
        response = self.manager.delete(f"/api/parties/{self.rental.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Party.objects.filter(id=self.rental.id).exists())
        self.assertTrue(Invoice.objects.filter(id=invoice.id).exists())

    def test_customer_with_message_history_cannot_be_deleted(self):
        message = Message.objects.create(party=self.rental, channel=Message.EMAIL, direction=Message.OUT, body="Historical record")
        response = self.manager.delete(f"/api/parties/{self.rental.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Message.objects.filter(id=message.id).exists())
        self.assertTrue(Party.objects.filter(id=self.rental.id).exists())

    def test_unused_customer_can_be_deleted(self):
        unused = Party.objects.create(name="Unused", type=Party.RETAIL, phone="9000000000", joined=date.today())
        response = self.manager.delete(f"/api/parties/{unused.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Party.objects.filter(id=unused.id).exists())

    @override_settings(BUSINESS_NAME="Test Laptops")
    @mock.patch("parties.views.send_email", return_value={"status": "sent"})
    @mock.patch("parties.views.send_whatsapp")
    def test_email_message_is_sent_to_the_party_once_and_marked_sent(self, send_whatsapp, send_email):
        for url in (f"/api/parties/{self.rental.id}/message/", f"/api/parties/{self.rental.id}/messages/"):
            send_email.reset_mock()
            response = self.manager.post(url, {"channel": "email", "body": "Invoice attached"}, format="json")
            self.assertEqual(response.status_code, 201)
            msg = Message.objects.get(id=response.json()["id"])
            self.assertEqual((msg.channel, msg.direction, msg.body), (Message.EMAIL, Message.OUT, "Invoice attached"))
            send_email.assert_called_once_with("ops@rental.example", "Message from Test Laptops", "Invoice attached")
            self.assertEqual((msg.delivery_status, msg.delivery_error), (Message.DELIVERY_SENT, ""))
            self.assertIsNotNone(msg.delivery_updated_at)
            self.assertEqual(response.json()["delivery_status"], "sent")
        send_whatsapp.assert_not_called()

    @mock.patch("parties.views.send_email", return_value={"status": "failed"})
    def test_failed_email_is_kept_in_history_and_marked_failed(self, send_email):
        response = self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "email", "body": "Hello"}, format="json")
        self.assertEqual(response.status_code, 201)
        msg = Message.objects.get(party=self.rental)
        self.assertEqual(msg.body, "Hello")
        self.assertEqual(msg.delivery_status, Message.DELIVERY_FAILED)
        self.assertIn("mail server", msg.delivery_error)
        self.assertEqual(response.json()["delivery_status"], "failed")
        self.assertEqual(response.json()["delivery_error"], msg.delivery_error)

    @mock.patch("parties.views.send_email", return_value={"status": "failed", "reason": "x" * 500})
    def test_email_failure_reason_is_cut_to_the_field_length(self, send_email):
        self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "email", "body": "Hello"}, format="json")
        self.assertEqual(len(Message.objects.get(party=self.rental).delivery_error),
                         Message._meta.get_field("delivery_error").max_length)

    def test_email_to_party_without_address_is_failed_not_sent(self):
        no_email = Party.objects.create(name="No Email", type=Party.RETAIL, phone="9000000009", joined=date.today())
        with mock.patch("django.core.mail.send_mail") as smtp:
            response = self.manager.post(f"/api/parties/{no_email.id}/messages/", {"channel": "email", "body": "Hi"}, format="json")
        smtp.assert_not_called()
        self.assertEqual(response.status_code, 201)
        msg = Message.objects.get(party=no_email)
        self.assertEqual((msg.delivery_status, msg.delivery_error), (Message.DELIVERY_FAILED, "party has no email on file"))

    @mock.patch("parties.views.send_email")
    @mock.patch("parties.views.party_whatsapp.deliver", side_effect=lambda message: message)
    def test_whatsapp_message_uses_whatsapp_pipeline_not_email(self, deliver, send_email):
        response = self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "whatsapp", "body": "Hi"}, format="json")
        self.assertEqual(response.status_code, 201)
        deliver.assert_called_once()
        self.assertEqual(deliver.call_args.args[0].channel, Message.WHATSAPP)
        send_email.assert_not_called()

    def test_message_creation_requires_manage_permission_and_valid_channel(self):
        forbidden = self.viewer.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "whatsapp", "body": "hello"}, format="json")
        self.assertEqual(forbidden.status_code, 403)
        invalid = self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "sms", "body": "hello"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(Message.objects.filter(party=self.rental).count(), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_portal_invite_for_every_customer_type(self):
        for kind in (Party.RETAIL, Party.DEALER):
            other = Party.objects.create(name=f"Walk-in {kind}", type=kind, phone="9000000001", email="w@x.example", joined=date.today())
            issued = self.manager.post(f"/api/parties/{other.id}/portal-invite/")
            self.assertEqual(issued.status_code, 201, issued.content)
        no_agreement = Party.objects.create(name="No agreement", type=Party.RENTAL, phone="9000000003", email="n@x.example", joined=date.today())
        refused = self.manager.post(f"/api/parties/{no_agreement.id}/portal-invite/")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("rental agreement", refused.json()["detail"])
        self.assertEqual(self.viewer.post(f"/api/parties/{self.rental.id}/portal-invite/").status_code, 403)

        response = self.manager.post(f"/api/parties/{self.rental.id}/portal-invite/")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["phone"], "****3210")
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(PortalInvite.objects.filter(party=self.rental).count(), 1)

        account = self.viewer.get(f"/api/parties/{self.rental.id}/portal-account/").json()
        self.assertEqual((account["enabled"], account["status"]), (True, "pending"))

        self.assertEqual(self.manager.post(f"/api/parties/{self.rental.id}/revoke-portal-access/").status_code, 200)
        revoked = self.viewer.get(f"/api/parties/{self.rental.id}/portal-account/").json()
        self.assertEqual(revoked["status"], "revoked")
        self.assertEqual(PortalInvite.objects.filter(party=self.rental).count(), 1)
        # reusable links must not survive a revoke
        self.assertFalse(PortalInvite.objects.get(party=self.rental).is_valid)

    def test_saved_whatsapp_message_edit_hide_and_shared_delete_are_scoped(self):
        created = self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "whatsapp", "body": "original\nline"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        message_id = created.json()["id"]
        self.assertTrue(created.json()["is_editable"])
        self.assertEqual(created.json()["body"], "original\nline")
        forbidden_edit = self.viewer.patch(f"/api/parties/{self.rental.id}/messages/{message_id}/", {"body": "unauthorized"}, format="json")
        self.assertEqual(forbidden_edit.status_code, 403)

        other_party = Party.objects.create(name="Other", type=Party.RETAIL, phone="9000000002", joined=date.today())
        wrong_customer = self.manager.patch(f"/api/parties/{other_party.id}/messages/{message_id}/", {"body": "wrong party"}, format="json")
        self.assertEqual(wrong_customer.status_code, 404)
        wrong_customer_hide = self.viewer.post(f"/api/parties/{other_party.id}/messages/{message_id}/hide/")
        self.assertEqual(wrong_customer_hide.status_code, 404)
        updated = self.manager.patch(f"/api/parties/{self.rental.id}/messages/{message_id}/", {"body": "updated\nline"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["id"], created.json()["id"])
        self.assertEqual(updated.json()["at"], created.json()["at"])
        self.assertIsNotNone(updated.json()["edited_at"])
        self.assertEqual(Message.objects.get(pk=message_id).revisions.count(), 1)

        self.assertEqual(self.viewer.post(f"/api/parties/{self.rental.id}/messages/{message_id}/hide/").status_code, 204)
        self.assertEqual(len(self.viewer.get(f"/api/parties/{self.rental.id}/").json()["messages"]), 0)
        self.assertEqual(len(self.manager.get(f"/api/parties/{self.rental.id}/").json()["messages"]), 1)

        forbidden = self.viewer.post(f"/api/parties/{self.rental.id}/messages/{message_id}/delete-for-everyone/")
        self.assertEqual(forbidden.status_code, 403)
        self.assertFalse(Message.objects.get(pk=message_id).deleted_at)

        removed = self.manager.post(f"/api/parties/{self.rental.id}/messages/{message_id}/delete-for-everyone/")
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.json()["is_deleted"])
        self.assertEqual(removed.json()["body"], "This message was deleted.")
        self.assertEqual(Message.objects.get(pk=message_id).body, "updated\nline")

    def test_email_history_is_copy_only_and_legacy_messages_are_immutable(self):
        email = Message.objects.create(party=self.rental, channel=Message.EMAIL, direction=Message.OUT, body="receipt")
        response = self.manager.patch(f"/api/parties/{self.rental.id}/messages/{email.id}/", {"body": "changed"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.manager.post(f"/api/parties/{self.rental.id}/messages/{email.id}/hide/").status_code, 409)
        self.assertEqual(email.body, Message.objects.get(pk=email.id).body)

        old = Message.objects.create(party=self.rental, channel=Message.WHATSAPP, direction=Message.OUT, body="historical")
        response = self.manager.patch(f"/api/parties/{self.rental.id}/messages/{old.id}/", {"body": "changed"}, format="json")
        self.assertEqual(response.status_code, 409)
        # PUT must not bypass the PATCH guards.
        response = self.manager.put(f"/api/parties/{self.rental.id}/messages/{old.id}/", {"channel": "whatsapp", "body": "changed"}, format="json")
        self.assertIn(response.status_code, (400, 409))
        response = self.manager.put(f"/api/parties/{self.rental.id}/messages/{email.id}/", {"body": "changed"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Message.objects.get(pk=old.id).body, "historical")

    def test_saved_message_channel_cannot_be_changed(self):
        created = self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": "whatsapp", "body": "hello"}, format="json")
        message_id = created.json()["id"]
        response = self.manager.patch(f"/api/parties/{self.rental.id}/messages/{message_id}/", {"channel": "email", "body": "hi"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.get(pk=message_id).channel, Message.WHATSAPP)

    def test_message_create_is_crm_only_and_email_records_are_persisted(self):
        for channel in (Message.WHATSAPP, Message.EMAIL):
            response = self.manager.post(f"/api/parties/{self.rental.id}/messages/", {"channel": channel, "body": "  saved note  "}, format="json")
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(response.json()["body"], "  saved note  ")
            self.assertTrue(response.json()["is_editable"])


    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_portal_link_is_emailed_and_recorded_on_both_threads(self):
        from django.core import mail

        response = self.manager.post(f"/api/parties/{self.rental.id}/portal-invite/")
        self.assertEqual(response.status_code, 201, response.content)
        link = response.json()["setup_url"]
        self.assertEqual(response.json()["email_sent_to"], "ops@rental.example")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ops@rental.example"])
        otp = re.search(r"code is (\d{6})", mail.outbox[0].body).group(1)
        self.assertTrue(PortalInvite.objects.get(party=self.rental).check_otp(otp))

        # the history records that the code went out, never the code (or its hash)
        email_record = Message.objects.get(party=self.rental, channel=Message.EMAIL)
        self.assertNotIn(otp, email_record.body)
        self.assertNotIn(PortalInvite.objects.get(party=self.rental).otp_digest, email_record.body)
        self.assertIn("code is ******", email_record.body)
        self.assertIn("delivery: sent", email_record.body)
        whatsapp_record = Message.objects.get(party=self.rental, channel=Message.WHATSAPP)
        self.assertIn(link, whatsapp_record.body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_portal_link_is_on_whatsapp_thread_even_without_whatsapp(self):
        Party.objects.filter(pk=self.rental.pk).update(whatsapp_verified=False)
        with mock.patch("portal.services.send_whatsapp") as send_whatsapp:
            response = self.manager.post(f"/api/parties/{self.rental.id}/portal-invite/")
        self.assertEqual(response.status_code, 201, response.content)
        send_whatsapp.assert_not_called()
        self.assertIn(response.json()["setup_url"], Message.objects.get(party=self.rental, channel=Message.WHATSAPP).body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_failed_email_creates_no_invite_or_messages(self):
        with mock.patch("portal.services.send_email", return_value={"status": "failed"}):
            response = self.manager.post(f"/api/parties/{self.rental.id}/portal-invite/")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PortalInvite.objects.filter(party=self.rental).exists())
        self.assertFalse(Message.objects.filter(party=self.rental).exists())

    def test_reset_link_requires_existing_portal_account(self):
        self.assertEqual(self.manager.post(f"/api/parties/{self.rental.id}/portal-reset-link/").status_code, 400)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_portal_link_works_end_to_end_without_smtp(self):
        from rest_framework.test import APIClient

        import io

        with mock.patch("sys.stdout", new_callable=io.StringIO) as console:  # the console backend prints the email
            response = self.manager.post(f"/api/parties/{self.rental.id}/portal-invite/")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["email_delivery"], "console")
        link = response.json()["setup_url"]
        token = link.rstrip("/").rsplit("/portal/", 1)[1]
        # in development the code reaches only the console "inbox"
        otp = re.search(r"code is (\d{6})", console.getvalue()).group(1)

        # Staff see the link on the CRM WhatsApp thread; the email thread keeps a masked record.
        thread = self.manager.get(f"/api/parties/{self.rental.id}/").json()["messages"]
        self.assertTrue(any(m["channel"] == "whatsapp" and link in m["body"] for m in thread))
        email = next(m for m in thread if m["channel"] == "email")
        self.assertNotIn(otp, email["body"])
        self.assertIn("delivery: console", email["body"])

        customer = APIClient()
        self.assertEqual(customer.get(f"/api/portal/invite-status/{token}/").status_code, 200)
        wrong = "000000" if otp != "000000" else "111111"
        self.assertEqual(customer.post("/api/portal/verify/", {"token": token, "otp": wrong}, format="json").status_code, 400)
        verified = customer.post("/api/portal/verify/", {"token": token, "otp": otp}, format="json")
        self.assertEqual(verified.status_code, 200, verified.content)

        customer.credentials(HTTP_AUTHORIZATION=f"Portal {verified.json()['portal_token']}")
        self.assertEqual(customer.get("/api/portal/me/").status_code, 200)
        # The link is reusable until it expires; the code itself is single-use.
        self.assertEqual(APIClient().get(f"/api/portal/invite-status/{token}/").status_code, 200)
        reused = APIClient().post("/api/portal/verify/", {"token": token, "otp": otp}, format="json")
        self.assertEqual((reused.status_code, reused.json()["code"]), (400, "otp_invalid"))

    def test_revoke_portal_access_stamps_time(self):
        response = self.manager.post(f"/api/parties/{self.rental.id}/revoke-portal-access/")
        self.assertEqual(response.status_code, 200)
        self.rental.refresh_from_db()
        self.assertIsNotNone(self.rental.portal_access_revoked_at)
