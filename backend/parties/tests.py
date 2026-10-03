import os
from datetime import date
from unittest import mock

from django.test import TestCase

from crmbook_backend.testing import client_for, make_user, results
from parties.models import Message, Party
from portal.models import PortalInvite


@mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"})
class PartyApiTests(TestCase):
    def setUp(self):
        self.manager = client_for(make_user("party-manager", ["parties.view", "parties.manage"]))
        self.viewer = client_for(make_user("party-viewer", ["parties.view"]))
        self.rental = Party.objects.create(
            name="Rental Corp", type=Party.RENTAL, phone="9876543210", email="ops@rental.example", joined=date.today()
        )

    def create_party(self, client, phone="9876501234"):
        return client.post("/api/parties/", {
            "name": "New Retail Customer", "type": Party.RETAIL, "phone": phone, "joined": date.today().isoformat(),
        }, format="json")

    def test_create_runs_whatsapp_check(self):
        good = self.create_party(self.manager)
        self.assertEqual(good.status_code, 201, good.content)
        self.assertTrue(Party.objects.get(id=good.json()["id"]).whatsapp_verified)

        bad = self.create_party(self.manager, phone="12345")
        self.assertFalse(Party.objects.get(id=bad.json()["id"]).whatsapp_verified)

    def test_phone_change_rechecks_whatsapp(self):
        response = self.manager.patch(f"/api/parties/{self.rental.id}/", {"phone": "011-2345"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.rental.refresh_from_db()
        self.assertFalse(self.rental.whatsapp_verified)

    def test_search_by_name(self):
        Party.objects.create(name="Someone Else", type=Party.RETAIL, phone="9000000000", joined=date.today())
        names = [p["name"] for p in results(self.viewer.get("/api/parties/", {"q": "rental"}))]
        self.assertEqual(names, ["Rental Corp"])

    def test_viewer_cannot_write(self):
        self.assertEqual(self.create_party(self.viewer).status_code, 403)
        self.assertEqual(self.viewer.post(f"/api/parties/{self.rental.id}/message/", {"body": "hi"}, format="json").status_code, 403)
        self.assertEqual(client_for(make_user("no-parties")).get("/api/parties/").status_code, 403)

    def test_send_message_is_logged_on_the_thread(self):
        response = self.manager.post(f"/api/parties/{self.rental.id}/message/", {"channel": "email", "body": "Invoice attached"}, format="json")
        self.assertEqual(response.status_code, 201)
        msg = Message.objects.get(party=self.rental)
        self.assertEqual((msg.channel, msg.direction, msg.body), (Message.EMAIL, Message.OUT, "Invoice attached"))

    def test_portal_invite_only_for_rental_customers(self):
        retail = Party.objects.create(name="Walk-in", type=Party.RETAIL, phone="9000000001", joined=date.today())
        self.assertEqual(self.manager.post(f"/api/parties/{retail.id}/portal-invite/").status_code, 400)

        response = self.manager.post(f"/api/parties/{self.rental.id}/portal-invite/")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["phone"], "****3210")
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(PortalInvite.objects.filter(party=self.rental).count(), 1)

        account = self.viewer.get(f"/api/parties/{self.rental.id}/portal-account/").json()
        self.assertEqual((account["enabled"], account["status"]), (True, "pending"))

    def test_reset_link_requires_existing_portal_account(self):
        self.assertEqual(self.manager.post(f"/api/parties/{self.rental.id}/portal-reset-link/").status_code, 400)

    def test_revoke_portal_access_stamps_time(self):
        response = self.manager.post(f"/api/parties/{self.rental.id}/revoke-portal-access/")
        self.assertEqual(response.status_code, 200)
        self.rental.refresh_from_db()
        self.assertIsNotNone(self.rental.portal_access_revoked_at)
