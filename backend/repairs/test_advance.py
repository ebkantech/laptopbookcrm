"""The 25% repair advance is a real invoice: raised at booking, deducted
from the final bill only once paid."""
import os
from datetime import date
from unittest import mock

from django.test import TestCase

from catalog.models import Service, StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from repairs.models import RepairTicket
from repairs.services import approve_on_behalf, finalize_estimate
from sales.models import Invoice


@mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"})
class RepairAdvanceTests(TestCase):
    def setUp(self):
        self.owner = make_user("adv-owner", superuser=True)
        self.client_ = client_for(self.owner)
        self.shop = StockPoint.objects.create(slug="shop", name="Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Repair Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        self.service = Service.objects.create(slug="screen", label="Screen replacement", segment=Service.HARDWARE, charge=4000)

    def book(self, payment=RepairTicket.ADVANCE):
        response = self.client_.post("/api/tickets/", {
            "party": self.party.id, "brand": "Dell", "model_name": "Inspiron", "serial": "SN-ADV-1",
            "stock_point": self.shop.id, "issue": "Cracked screen", "service_ids": [self.service.id],
            "payment": payment, "advance_paid": 99999, "received": date.today().isoformat(),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return RepairTicket.objects.get(pk=response.json()["id"])

    def approve(self, ticket):
        RepairTicket.objects.filter(pk=ticket.pk).update(status=RepairTicket.DIAGNOSING)
        ticket.refresh_from_db()
        finalize_estimate(ticket, self.owner, [{"service": self.service, "description": "Screen replacement", "quantity": 1, "unit_price": 4000}])
        approve_on_behalf(ticket, self.owner, "Approved at the counter")

    def pay(self, invoice):
        return self.client_.post(f"/api/invoices/{invoice.id}/settle/", {"pay_method": "Cash"}, format="json")

    def test_booking_raises_an_advance_invoice_and_ignores_client_amount(self):
        ticket = self.book()
        self.assertEqual(ticket.advance_paid, 0)  # nothing received yet
        advance = Invoice.objects.get(repair_ticket=ticket, is_advance=True)
        self.assertEqual((advance.total, advance.status, advance.due_date), (1000, Invoice.LINK_SENT, date.today()))
        data = self.client_.get(f"/api/tickets/{ticket.id}/").json()
        self.assertEqual(data["advance_invoice"]["code"], advance.code)
        self.assertIsNone(data["pending_invoice"])  # the advance doesn't hold the ticket at pickup

    def test_pay_on_delivery_raises_no_advance(self):
        ticket = self.book(payment=RepairTicket.FULL)
        self.assertFalse(Invoice.objects.filter(repair_ticket=ticket).exists())

    def test_work_waits_for_the_advance_then_final_bill_deducts_it(self):
        ticket = self.book()
        self.approve(ticket)
        blocked = self.client_.post(f"/api/tickets/{ticket.id}/advance/")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Advance invoice", blocked.json()["detail"])

        advance = Invoice.objects.get(repair_ticket=ticket, is_advance=True)
        self.assertEqual(self.pay(advance).status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual((ticket.advance_paid, ticket.status), (1000, RepairTicket.DIAGNOSING))  # not delivered by the advance
        self.assertEqual(self.client_.post(f"/api/tickets/{ticket.id}/advance/").status_code, 200)

        RepairTicket.objects.filter(pk=ticket.pk).update(status=RepairTicket.READY)
        self.client_.post(f"/api/tickets/{ticket.id}/settle/")
        final = Invoice.objects.get(repair_ticket=ticket, is_advance=False)
        self.assertEqual(final.total, 4000 - 1000)
        self.pay(final)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, RepairTicket.DELIVERED)

    def test_unpaid_advance_is_rolled_into_the_final_bill(self):
        ticket = self.book()
        self.approve(ticket)
        RepairTicket.objects.filter(pk=ticket.pk).update(status=RepairTicket.READY)
        self.client_.post(f"/api/tickets/{ticket.id}/settle/")
        advance = Invoice.objects.get(repair_ticket=ticket, is_advance=True)
        self.assertEqual(advance.status, Invoice.CANCELLED)
        self.assertEqual(Invoice.objects.get(repair_ticket=ticket, is_advance=False).total, 4000)

    def test_refunding_the_advance_reduces_what_is_deducted(self):
        ticket = self.book()
        advance = Invoice.objects.get(repair_ticket=ticket, is_advance=True)
        self.pay(advance)
        response = self.client_.post(f"/api/invoices/{advance.id}/refund/", {"amount": 400, "method": "Cash", "reason": "Job reduced"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.advance_paid, 600)

    def test_bulk_order_raises_an_advance_per_device(self):
        response = self.client_.post("/api/repair-orders/", {
            "party": self.party.id, "stock_point": self.shop.id, "received": date.today().isoformat(), "payment": RepairTicket.ADVANCE,
            "devices": [
                {"brand": "Dell", "model_name": "A", "serial": "B-1", "issue": "x", "service_ids": [self.service.id]},
                {"brand": "HP", "model_name": "B", "serial": "B-2", "issue": "y", "service_ids": [self.service.id]},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Invoice.objects.filter(is_advance=True).count(), 2)
