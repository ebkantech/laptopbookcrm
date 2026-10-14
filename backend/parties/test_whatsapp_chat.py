"""CRM chat -> WhatsApp Cloud API (Parties chat and Rentals "Chat on WhatsApp"
use the same endpoint). Meta is always mocked; nothing is really sent."""
import hashlib
import hmac
import json
import os
from datetime import date, timedelta
from unittest import mock

import requests
from django.test import TestCase, override_settings
from django.utils import timezone

from crmbook_backend.testing import client_for, make_user
from parties.models import Message, Party
from portal.models import WhatsAppDeliveryLog
from rentals.models import Rental

META_ENV = {"WHATSAPP_PROVIDER": "meta_cloud", "WHATSAPP_PHONE_NUMBER_ID": "123456789012345",
            "WHATSAPP_ACCESS_TOKEN": "secret-token-xyz", "WHATSAPP_GRAPH_API_VERSION": ""}
APP_SECRET = "test-app-secret"


def accepted(message_id="wamid.CHAT1"):
    return mock.Mock(status_code=200, **{"json.return_value": {"messages": [{"id": message_id}]}})


def rejected(code=131030, status=400):
    return mock.Mock(status_code=status, **{"json.return_value": {"error": {"code": code, "message": "rejected"}}})


class WhatsAppChatBase(TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, META_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.manager = client_for(make_user("chat-manager", ["parties.view", "parties.manage"]))
        self.viewer = client_for(make_user("chat-viewer", ["parties.view", "rentals.view"]))
        self.party = Party.objects.create(name="Akif Rentals", type=Party.RENTAL, phone="98765 43210", joined=date.today())
        self.other = Party.objects.create(name="Someone Else", type=Party.RETAIL, phone="9123456780", joined=date.today())

    def post(self, body="Hello from the CRM", party=None, client=None, channel="whatsapp", response=None, side_effect=None, extra=None):
        payload = {"channel": channel, "body": body, **(extra or {})}
        with mock.patch("requests.post", return_value=response or accepted(), side_effect=side_effect) as post:
            result = (client or self.manager).post(f"/api/parties/{(party or self.party).pk}/messages/", payload, format="json")
        return result, post

    def retry(self, message_id, confirm=False, response=None, side_effect=None, client=None):
        with mock.patch("requests.post", return_value=response or accepted("wamid.RETRY"), side_effect=side_effect) as post:
            result = (client or self.manager).post(f"/api/parties/{self.party.pk}/messages/{message_id}/retry/",
                                                   {"confirm": confirm}, format="json")
        return result, post


class SendTests(WhatsAppChatBase):
    def test_whatsapp_message_is_sent_through_the_cloud_api(self):
        response, post = self.post("Your laptop is ready")
        self.assertEqual(response.status_code, 201, response.content)
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["to"], "919876543210")  # the party's own number, normalized
        self.assertEqual(payload["text"]["body"], "Your laptop is ready")
        data = response.json()
        self.assertEqual(data["delivery_status"], "sent")
        self.assertFalse(data["is_editable"])  # an accepted WhatsApp can't be edited
        self.assertNotIn("provider_message_id", data)
        self.assertNotIn("secret-token-xyz", response.content.decode())
        message = Message.objects.get(pk=data["id"])
        self.assertEqual((message.provider_message_id, message.direction), ("wamid.CHAT1", Message.OUT))
        self.assertTrue(WhatsAppDeliveryLog.objects.filter(provider_message_id="wamid.CHAT1", party=self.party).exists())

    def test_server_uses_the_party_number_not_one_from_the_request(self):
        response, post = self.post(extra={"phone": "911111111111", "to": "911111111111", "party": self.other.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(post.call_args.kwargs["json"]["to"], "919876543210")
        self.assertEqual(Message.objects.get(pk=response.json()["id"]).party, self.party)

    def test_email_messages_go_by_smtp_not_whatsapp(self):
        with mock.patch("parties.views.send_email", return_value={"status": "sent"}) as send_email:
            response, post = self.post(channel="email")
        self.assertEqual(response.status_code, 201)
        post.assert_not_called()
        send_email.assert_called_once()
        self.assertEqual(response.json()["delivery_status"], "sent")

    def test_rejection_is_saved_as_failed_with_the_reason(self):
        response, _ = self.post(response=rejected(131030))
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["delivery_status"], "failed")
        self.assertIn("allowed recipient list", data["delivery_error"])
        self.assertTrue(data["is_editable"])
        self.assertEqual(Message.objects.get(pk=data["id"]).provider_message_id, "")
        self.assertFalse(WhatsAppDeliveryLog.objects.exists())

    def test_missing_configuration_fails_without_calling_meta(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_ACCESS_TOKEN": ""}):
            response, post = self.post()
        post.assert_not_called()
        self.assertEqual(response.json()["delivery_status"], "failed")
        self.assertIn("WHATSAPP_ACCESS_TOKEN", response.json()["delivery_error"])

    def test_missing_phone_number(self):
        Party.objects.filter(pk=self.party.pk).update(phone="")
        response, post = self.post()
        post.assert_not_called()
        self.assertEqual(response.json()["delivery_status"], "failed")
        self.assertIn("no phone number", response.json()["delivery_error"])

    def test_invalid_phone_number(self):
        Party.objects.filter(pk=self.party.pk).update(phone="12-34")
        response, post = self.post()
        post.assert_not_called()
        self.assertEqual(response.json()["delivery_status"], "failed")
        self.assertIn("valid WhatsApp number", response.json()["delivery_error"])

    def test_timeout_is_uncertain_not_failed(self):
        response, _ = self.post(side_effect=requests.Timeout())
        self.assertEqual(response.json()["delivery_status"], "unknown")

    def test_console_mode_is_reported_as_simulated(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"}):
            response, post = self.post()
        post.assert_not_called()
        self.assertEqual(response.json()["delivery_status"], "simulated")

    def test_whatsapp_length_limit(self):
        response, post = self.post(body="x" * 4097)
        self.assertEqual(response.status_code, 400)
        post.assert_not_called()
        self.assertFalse(Message.objects.exists())

    def test_unauthorized_users_cannot_send(self):
        response, post = self.post(client=self.viewer)
        self.assertEqual(response.status_code, 403)
        post.assert_not_called()
        anonymous, post = self.post(client=self.client)
        self.assertEqual(anonymous.status_code, 401)
        post.assert_not_called()
        self.assertFalse(Message.objects.exists())

    def test_legacy_message_endpoint_sends_too(self):
        with mock.patch("requests.post", return_value=accepted()) as post:
            response = self.manager.post(f"/api/parties/{self.party.pk}/message/", {"channel": "whatsapp", "body": "hi"}, format="json")
        self.assertEqual(response.status_code, 201)
        post.assert_called_once()
        self.assertEqual(response.json()["delivery_status"], "sent")

    def test_rental_customer_chat_sends_to_the_rental_party(self):
        """Rentals > Chat on WhatsApp opens the same composer for rental.party."""
        rental = Rental.objects.create(party=self.party, product_label="Dell", monthly_fee=1500, start=date.today(),
                                       tenure_months=6, last_payment=date.today(), status=Rental.ACTIVE)
        response, post = self.post(party=rental.party)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(post.call_args.kwargs["json"]["to"], "919876543210")


class RetryTests(WhatsAppChatBase):
    def test_failed_message_is_retried_in_place(self):
        failed, _ = self.post(response=rejected())
        message_id = failed.json()["id"]
        response, post = self.retry(message_id)
        self.assertEqual(response.status_code, 200, response.content)
        post.assert_called_once()
        self.assertEqual(response.json()["delivery_status"], "sent")
        self.assertEqual(Message.objects.count(), 1)  # same row, no duplicate

    def test_edited_failed_message_resends_the_edited_text(self):
        failed, _ = self.post(response=rejected())
        message_id = failed.json()["id"]
        edit = self.manager.patch(f"/api/parties/{self.party.pk}/messages/{message_id}/", {"body": "Corrected"}, format="json")
        self.assertEqual(edit.status_code, 200)
        _, post = self.retry(message_id)
        self.assertEqual(post.call_args.kwargs["json"]["text"]["body"], "Corrected")

    def test_sent_message_is_never_resent(self):
        sent, _ = self.post()
        response, post = self.retry(sent.json()["id"], confirm=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "already_sent")
        post.assert_not_called()

    def test_uncertain_message_needs_confirmation(self):
        unknown, _ = self.post(side_effect=requests.Timeout())
        message_id = unknown.json()["id"]
        refused, post = self.retry(message_id)
        self.assertEqual((refused.status_code, refused.json()["code"]), (409, "confirm_required"))
        post.assert_not_called()
        confirmed, post = self.retry(message_id, confirm=True)
        self.assertEqual(confirmed.json()["delivery_status"], "sent")
        post.assert_called_once()

    def test_message_already_sending_is_not_sent_twice(self):
        failed, _ = self.post(response=rejected())
        Message.objects.filter(pk=failed.json()["id"]).update(delivery_status="sending", delivery_updated_at=timezone.now())
        response, post = self.retry(failed.json()["id"], confirm=True)
        self.assertEqual((response.status_code, response.json()["code"]), (409, "in_progress"))
        post.assert_not_called()

    def test_stale_sending_counts_as_uncertain(self):
        failed, _ = self.post(response=rejected())
        Message.objects.filter(pk=failed.json()["id"]).update(delivery_status="sending",
                                                              delivery_updated_at=timezone.now() - timedelta(minutes=10))
        refused, _ = self.retry(failed.json()["id"])
        self.assertEqual(refused.json()["code"], "confirm_required")
        confirmed, post = self.retry(failed.json()["id"], confirm=True)
        self.assertEqual(confirmed.json()["delivery_status"], "sent")

    def test_uncertain_and_sending_messages_cannot_be_edited(self):
        unknown, _ = self.post(side_effect=requests.Timeout())
        edit = self.manager.patch(f"/api/parties/{self.party.pk}/messages/{unknown.json()['id']}/", {"body": "x"}, format="json")
        self.assertEqual(edit.status_code, 409)

    def test_crm_only_history_and_deleted_messages_cannot_be_retried(self):
        email, _ = self.post(channel="email")
        response, post = self.retry(email.json()["id"])
        self.assertEqual(response.status_code, 409)
        failed, _ = self.post(response=rejected())
        self.manager.post(f"/api/parties/{self.party.pk}/messages/{failed.json()['id']}/delete-for-everyone/", {}, format="json")
        response, post = self.retry(failed.json()["id"])
        self.assertEqual(response.status_code, 409)
        post.assert_not_called()

    def test_retry_requires_manage_permission(self):
        failed, _ = self.post(response=rejected())
        response, post = self.retry(failed.json()["id"], client=self.viewer)
        self.assertEqual(response.status_code, 403)
        post.assert_not_called()


@override_settings(WHATSAPP_APP_SECRET=APP_SECRET, WHATSAPP_WEBHOOK_VERIFY_TOKEN="verify-me")
class MetaWebhookTests(WhatsAppChatBase):
    URL = "/api/whatsapp/meta-webhook/"

    def hook(self, statuses, secret=APP_SECRET):
        body = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"statuses": statuses}}]}]}).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(self.URL, body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature)

    def sent_message(self):
        response, _ = self.post()
        return Message.objects.get(pk=response.json()["id"])

    def test_verification_handshake(self):
        ok = self.client.get(self.URL, {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
        self.assertEqual((ok.status_code, ok.content), (200, b"12345"))
        bad = self.client.get(self.URL, {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"})
        self.assertEqual(bad.status_code, 403)

    def test_delivered_and_read_only_come_from_the_webhook(self):
        message = self.sent_message()
        self.assertEqual(message.delivery_status, "sent")
        self.hook([{"id": "wamid.CHAT1", "status": "delivered"}])
        message.refresh_from_db()
        self.assertEqual(message.delivery_status, "delivered")
        self.hook([{"id": "wamid.CHAT1", "status": "read"}])
        self.hook([{"id": "wamid.CHAT1", "status": "delivered"}])  # late, out of order
        message.refresh_from_db()
        self.assertEqual(message.delivery_status, "read")
        self.assertEqual(WhatsAppDeliveryLog.objects.get(provider_message_id="wamid.CHAT1").status, "delivered")

    def test_async_failure_is_recorded(self):
        message = self.sent_message()
        self.hook([{"id": "wamid.CHAT1", "status": "failed", "errors": [{"code": 131047, "title": "Re-engagement message"}]}])
        message.refresh_from_db()
        self.assertEqual(message.delivery_status, "failed")
        self.assertIn("131047", message.delivery_error)

    def test_bad_or_missing_signature_is_refused(self):
        message = self.sent_message()
        self.assertEqual(self.hook([{"id": "wamid.CHAT1", "status": "delivered"}], secret="wrong").status_code, 403)
        unsigned = self.client.post(self.URL, b"{}", content_type="application/json")
        self.assertEqual(unsigned.status_code, 403)
        message.refresh_from_db()
        self.assertEqual(message.delivery_status, "sent")

    @override_settings(WHATSAPP_APP_SECRET=None)
    def test_refuses_everything_without_an_app_secret(self):
        self.assertEqual(self.hook([{"id": "x", "status": "delivered"}]).status_code, 403)

    def test_malformed_payloads_do_not_crash(self):
        for raw in (b"not json", b"[]", b'{"entry": "x"}', b'{"entry": [{"changes": [{"value": null}]}]}'):
            signature = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            response = self.client.post(self.URL, raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature)
            self.assertIn(response.status_code, (200, 400), raw)
