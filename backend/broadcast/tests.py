from datetime import date

from django.test import TestCase

from broadcast.models import Campaign, WhatsAppOrder
from crmbook_backend.testing import client_for, make_user
from parties.models import Party


class CampaignTests(TestCase):
    def test_create_campaign_records_simulated_delivery_numbers(self):
        marketer = client_for(make_user("marketer", ["broadcast.send"]))
        response = marketer.post("/api/campaigns/", {
            "title": "Diwali offer", "channel": Campaign.WHATSAPP, "audience": "All retail",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        campaign = Campaign.objects.get()
        self.assertGreater(campaign.sent, 0)
        self.assertLessEqual(campaign.opened, campaign.sent)

    def test_requires_broadcast_send(self):
        self.assertEqual(client_for(make_user("no-broadcast")).get("/api/campaigns/").status_code, 403)


class WhatsAppOrderTests(TestCase):
    def setUp(self):
        party = Party.objects.create(name="Order Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        self.order = WhatsAppOrder.objects.create(party=party, text="Need 2x ThinkPad T14")

    def test_quote_moves_order_to_quoted(self):
        staff = client_for(make_user("order-desk", ["orders.manage"]))
        response = staff.post(f"/api/whatsapp-orders/{self.order.id}/quote/")
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, WhatsAppOrder.QUOTED)

    def test_requires_orders_manage(self):
        nobody = client_for(make_user("no-orders"))
        self.assertEqual(nobody.get("/api/whatsapp-orders/").status_code, 403)
        self.assertEqual(nobody.post(f"/api/whatsapp-orders/{self.order.id}/quote/").status_code, 403)
