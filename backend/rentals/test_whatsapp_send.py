"""Sending a rental approval link through the WhatsApp API -- Meta is mocked."""
import shutil
import tempfile
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings

from crmbook_backend.testing import client_for, complete_handover, make_user
from parties.models import Party
from portal.models import WhatsAppDeliveryLog
from rentals.models import Rental, RentalApproval, RentalAsset, RentalEvent, RentalLine

TEST_MEDIA = tempfile.mkdtemp(prefix="crmbook-wa-send-media-")
META_ENV = {"WHATSAPP_PROVIDER": "meta_cloud", "WHATSAPP_PHONE_NUMBER_ID": "123456789012345",
            "WHATSAPP_ACCESS_TOKEN": "secret-token", "WHATSAPP_TEMPLATE_RENTAL_APPROVAL": ""}


def accepted(message_id="wamid.OK"):
    return mock.Mock(status_code=200, **{"json.return_value": {"messages": [{"id": message_id}]}})


def rejected(code=131030):
    return mock.Mock(status_code=400, **{"json.return_value": {"error": {"code": code, "message": "nope"}}})


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class ApprovalLinkWhatsAppSendTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = make_user("rental-wa-manager", ["rentals.view", "rentals.manage"])
        self.manager = client_for(self.user)
        self.party = Party.objects.create(name="Akif Traders", type=Party.RENTAL, phone="9876543210", joined=date.today())
        self.rental = self._rental("RNT-WA-1", "SN-WA-1")
        env = mock.patch.dict("os.environ", META_ENV)
        env.start()
        self.addCleanup(env.stop)

    def _rental(self, code, serial):
        rental = Rental.objects.create(
            party=self.party, agreement_code=code, product_label="1 device", monthly_fee=2000,
            start=date.today(), tenure_months=6, last_payment=date.today(),
        )
        asset = RentalAsset.objects.create(asset_tag=f"AST-{serial}", serial_number=serial, brand="Dell",
                                           model_name="Latitude", status=RentalAsset.RESERVED)
        complete_handover(RentalLine.objects.create(rental=rental, asset=asset, monthly_fee=2000), self.user)
        return rental

    def issue(self, rental=None):
        response = self.manager.post(f"/api/rentals/{(rental or self.rental).pk}/approval-link/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.data

    def send(self, url, rental=None, response=None):
        with mock.patch("requests.post", return_value=response or accepted()) as post:
            result = self.manager.post(f"/api/rentals/{(rental or self.rental).pk}/approval-link/send-whatsapp/",
                                       {"approval_url": url}, format="json")
        return result, post

    def wa_metadata(self, approval):
        event = RentalEvent.objects.get(approval=approval, event_type=RentalEvent.APPROVAL_LINK_CREATED)
        return event.metadata.get("whatsapp_api")

    def test_issue_reports_the_provider_and_keeps_existing_fields(self):
        data = self.issue()
        self.assertEqual(data["whatsapp_provider"], "meta_cloud")
        for key in ("approval_url", "whatsapp_url", "expires_at", "expires_in_hours", "version", "rental"):
            self.assertIn(key, data)

    def test_generating_a_link_alone_sends_nothing(self):
        with mock.patch("requests.post") as post:
            self.issue()
        post.assert_not_called()

    def test_send_uses_the_existing_link_without_a_new_approval(self):
        data = self.issue()
        approval = RentalApproval.objects.get(rental=self.rental)
        response, post = self.send(data["approval_url"])
        self.assertEqual(response.status_code, 200, response.content)
        delivery = response.data["whatsapp_delivery"]
        self.assertEqual((delivery["status"], delivery["provider_id"]), ("sent", "wamid.OK"))
        # same link, same approval row -- nothing re-issued
        self.assertEqual(RentalApproval.objects.filter(rental=self.rental).count(), 1)
        self.assertEqual(RentalApproval.objects.get(rental=self.rental).token_hash, approval.token_hash)
        self.assertIn(data["approval_url"], post.call_args.kwargs["json"]["text"]["body"])
        self.assertEqual(post.call_args.kwargs["json"]["to"], "919876543210")
        self.assertEqual(self.wa_metadata(approval)["status"], "sent")
        self.assertTrue(WhatsAppDeliveryLog.objects.filter(provider_message_id="wamid.OK", party=self.party).exists())
        self.assertNotIn("secret-token", str(response.data))

    def test_configured_template_is_used(self):
        data = self.issue()
        with mock.patch.dict("os.environ", {"WHATSAPP_TEMPLATE_RENTAL_APPROVAL": "rental_approval_link", "WHATSAPP_TEMPLATE_LANGUAGE": "en_US"}):
            response, post = self.send(data["approval_url"])
        self.assertEqual(response.data["whatsapp_delivery"]["template"], "rental_approval_link")
        params = [p["text"] for p in post.call_args.kwargs["json"]["template"]["components"][0]["parameters"]]
        self.assertEqual(params, ["Akif Traders", "RNT-WA-1", data["approval_url"]])

    def test_rejected_send_is_not_recorded_as_sent(self):
        data = self.issue()
        response, _ = self.send(data["approval_url"], response=rejected())
        self.assertEqual(response.status_code, 200)
        delivery = response.data["whatsapp_delivery"]
        self.assertEqual(delivery["status"], "failed")
        self.assertIsNone(delivery["provider_id"])
        self.assertIn("allowed recipient list", delivery["reason"])
        self.assertEqual(self.wa_metadata(RentalApproval.objects.get(rental=self.rental))["status"], "failed")
        self.assertFalse(WhatsAppDeliveryLog.objects.exists())
        # a failed attempt can be retried with the same link
        retry, _ = self.send(data["approval_url"])
        self.assertEqual(retry.data["whatsapp_delivery"]["status"], "sent")

    def test_accepted_link_is_not_sent_twice(self):
        data = self.issue()
        self.send(data["approval_url"])
        again, post = self.send(data["approval_url"])
        self.assertEqual(again.status_code, 409)
        post.assert_not_called()
        self.assertEqual(WhatsAppDeliveryLog.objects.count(), 1)

    def test_superseded_link_is_refused(self):
        old = self.issue()
        self.issue()
        response, post = self.send(old["approval_url"])
        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    def test_link_from_another_agreement_or_garbage_is_refused(self):
        other = self._rental("RNT-WA-2", "SN-WA-2")
        other_link = self.issue(other)["approval_url"]
        self.issue()
        for url in (other_link, "https://example.com/rental-approval/not-a-token", "", None):
            response, post = self.send(url)
            self.assertEqual(response.status_code, 400, url)
            post.assert_not_called()

    def test_console_mode_reports_simulated_not_sent(self):
        data = self.issue()
        with mock.patch.dict("os.environ", {"WHATSAPP_PROVIDER": "console"}):
            response, post = self.send(data["approval_url"])
        post.assert_not_called()
        self.assertEqual(response.data["whatsapp_delivery"]["status"], "simulated")
        self.assertFalse(WhatsAppDeliveryLog.objects.exists())

    def test_needs_rentals_manage(self):
        data = self.issue()
        viewer = client_for(make_user("rental-wa-viewer", ["rentals.view"]))
        with mock.patch("requests.post") as post:
            response = viewer.post(f"/api/rentals/{self.rental.pk}/approval-link/send-whatsapp/",
                                   {"approval_url": data["approval_url"]}, format="json")
        self.assertEqual(response.status_code, 403)
        post.assert_not_called()
