"""Rental and repair invoices go out with their payment link."""
from datetime import date
from unittest import mock

from django.core import mail
from rest_framework.test import APIClient

from crmbook_backend.testing import client_for, give_out, make_user
from parties.models import Message, Party
from portal.auth import issue_portal_token
from rentals import onboarding
from rentals.billing import raise_rent_invoice, send_due_rent_invoices
from rentals.models import Rental, add_months
from rentals.test_onboarding import Base as RentalBase
from repairs.models import RepairTicket
from repairs.test_revisions import ADMIN, Base
from sales import payments
from sales.models import Invoice, PaymentLink


class RepairLinkTests(Base):
    def setUp(self):
        super().setUp()
        self.boss = make_user("boss", ADMIN + ("invoices.view", "invoices.settle", "invoices.create"), stock_point=self.store)
        self.client_ = client_for(self.boss)

    def booked(self, payment):
        r = self.client_.post("/api/tickets/", {
            "party": self.party.pk, "brand": "Dell", "model_name": "L5", "serial": "S1", "stock_point": self.store.pk,
            "issue": "x", "received": date.today().isoformat(), "payment": payment, "service_ids": [self.service.pk],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return RepairTicket.objects.get(pk=r.data["id"])

    def test_advance_invoice_goes_with_its_link(self):
        ticket = self.booked(RepairTicket.ADVANCE)
        link = PaymentLink.objects.get(invoice__repair_ticket=ticket)
        self.assertEqual((link.upi_check, link.sent_by), (PaymentLink.UPI_NOT_CHECKED, self.boss))
        self.assertTrue(ticket.notifications.filter(channel="whatsapp", text__contains=link.url).exists())

    def test_final_invoice_goes_with_its_link(self):
        ticket = self.booked(RepairTicket.FULL)
        self.approve_current(ticket)
        give_out(ticket, self.staff)
        RepairTicket.objects.filter(pk=ticket.pk).update(status=RepairTicket.READY)
        self.assertEqual(self.client_.post(f"/api/tickets/{ticket.pk}/settle/").status_code, 200)
        link = PaymentLink.objects.get(invoice__repair_ticket=ticket)
        self.assertTrue(ticket.notifications.filter(text__contains=link.url).exists())
        self.assertTrue(Message.objects.filter(party=self.party, channel=Message.SMS, body__contains=link.url).exists())

    @mock.patch("sales.payments.create_upi_link", side_effect=payments.PaymentProviderError("down"))
    def test_provider_failure_keeps_the_invoice(self, _):
        ticket = self.booked(RepairTicket.ADVANCE)
        self.assertTrue(Invoice.objects.filter(repair_ticket=ticket).exists())
        self.assertFalse(PaymentLink.objects.exists())

    def test_customer_without_a_valid_number_gets_no_link(self):
        Party.objects.filter(pk=self.party.pk).update(phone="123")
        ticket = self.booked(RepairTicket.ADVANCE)
        self.assertTrue(Invoice.objects.filter(repair_ticket=ticket).exists())
        self.assertFalse(PaymentLink.objects.exists())

    @mock.patch("sales.payments.create_upi_link", return_value={"provider_link_id": "x", "url": "https://rzp.io/l/a", "sms_sent_by_provider": True})
    def test_no_second_link_for_the_same_invoice(self, maker):
        ticket = self.booked(RepairTicket.ADVANCE)
        invoice = Invoice.objects.get(repair_ticket=ticket)
        self.assertEqual(payments.send_invoice_link(invoice), "https://rzp.io/l/a")
        self.assertEqual(maker.call_count, 1)


class RentalLinkTests(RentalBase):
    def test_deposit_and_advance_go_with_their_links(self):
        rental = self.create()
        deposit, advance = onboarding.deposit_invoice(rental), onboarding.advance_invoice(rental)
        message = Message.objects.filter(party=self.party, channel=Message.WHATSAPP).latest("id")
        for invoice in (deposit, advance):
            self.assertIn(invoice.payment_links.get().url, message.body)
        self.assertIn(deposit.payment_links.get().url, mail.outbox[-1].body)

    def test_rent_change_replaces_the_link(self):
        rental = self.create()
        deposit = onboarding.deposit_invoice(rental)
        old = deposit.payment_links.get()
        rental.lines.update(monthly_fee=3000)
        rental.refresh_from_db()
        Rental.objects.filter(pk=rental.pk).update(monthly_fee=3000)
        rental.refresh_from_db()
        onboarding.sync_amounts(rental)
        old.refresh_from_db()
        self.assertEqual(old.status, PaymentLink.CANCELLED)
        self.assertEqual(deposit.payment_links.get(status=PaymentLink.SENT).amount, 3000)

    def active(self):
        rental = self.create()
        onboarding.deposit_invoice(rental)
        Rental.objects.filter(pk=rental.pk).update(status=Rental.ACTIVE, auto_invoice=True, months_paid=1,
                                                   requires_onboarding=False)
        rental.refresh_from_db()
        return rental

    def test_rent_invoice_goes_with_its_link(self):
        rental = self.active()
        invoice = raise_rent_invoice(rental, stock_point=self.shop, sent_by=self.user)
        link = invoice.payment_links.get()
        self.assertIn(link.url, Message.objects.filter(party=self.party, channel=Message.WHATSAPP).latest("id").body)

    def test_scheduler_sends_links_with_no_staff_member(self):
        rental = self.active()
        raised = send_due_rent_invoices(today=add_months(rental.start, 6))["raised"]
        link = Invoice.objects.get(code=raised[0]).payment_links.get()
        self.assertIsNone(link.sent_by)
        row = self.client.get(f"/api/invoices/{link.invoice_id}/").json()["payment_links"][0]
        self.assertEqual(row["sent_by_name"], "Automatic")


class RepairChatTests(RepairLinkTests):
    def test_links_reach_the_whatsapp_thread_for_copying(self):
        ticket = self.booked(RepairTicket.ADVANCE)
        bodies = " ".join(Message.objects.filter(party=self.party, channel=Message.WHATSAPP).values_list("body", flat=True))
        self.assertIn("/repair-approval/", bodies)
        self.assertIn(PaymentLink.objects.get(invoice__repair_ticket=ticket).url, bodies)


class CashTests(RepairLinkTests):
    def paid_in_cash(self, invoice):
        response = self.client_.post(f"/api/invoices/{invoice.pk}/settle/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def portal(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Portal {issue_portal_token(self.party)}")
        return client

    def test_cash_on_a_repair_advance_shows_paid_and_stops_the_link(self):
        ticket = self.booked(RepairTicket.ADVANCE)
        invoice = Invoice.objects.get(repair_ticket=ticket)
        self.paid_in_cash(invoice)
        self.assertEqual(invoice.payment_links.get().status, PaymentLink.CANCELLED)
        row = self.portal().get("/api/portal/repairs/").json()["invoices"][0]
        self.assertEqual((row["status"], row["payment_url"]), ("Paid", None))

    def test_portal_shows_store_stages_and_link(self):
        ticket = self.booked(RepairTicket.ADVANCE)
        data = self.portal().get("/api/portal/repairs/").json()
        self.assertEqual(data["tickets"][0]["store_name"], self.store.name)
        self.assertEqual(data["tickets"][0]["stages"][0], "Received")
        self.assertEqual(data["invoices"][0]["payment_url"], PaymentLink.objects.get(invoice__repair_ticket=ticket).url)


class RentalCashTests(RentalBase):
    def test_cash_on_deposit_and_rent_shows_paid(self):
        rental = self.create()
        deposit = onboarding.deposit_invoice(rental)
        self.pay(deposit)
        self.assertEqual(deposit.payment_links.get().status, PaymentLink.CANCELLED)
        Rental.objects.filter(pk=rental.pk).update(status=Rental.ACTIVE)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Portal {issue_portal_token(self.party)}")
        row = client.get("/api/portal/rentals/").json()[0]
        self.assertEqual(row["security_deposit"]["status"], "Paid")
        self.assertIsNone(row["security_deposit"]["payment_url"])
        self.assertNotIn(deposit.code, [d["code"] for d in row["payments_due"]])
