"""A repair goes booked -> assigned -> worked -> paid. Nothing jumps ahead."""
from datetime import date, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from crmbook_backend.testing import client_for, give_out, make_user
from parties.models import Party
from rentals.models import Rental
from portal.access import invite_closed_code
from portal.auth import issue_portal_token
from portal.services import create_portal_invite
from repairs.models import RepairTicket
from repairs.test_revisions import ADMIN, Base
from sales.models import Invoice


class JobOrderTests(Base):
    def setUp(self):
        super().setUp()
        self.boss = make_user("boss", ADMIN + ("invoices.view", "invoices.settle", "invoices.create"), stock_point=self.store)
        self.client_ = client_for(self.boss)
        self.ticket = RepairTicket.objects.get(pk=self.book(self.boss).data["id"])
        self.approve_current(self.ticket)

    def stage(self, status, client=None, **extra):
        return (client or self.client_).post(f"/api/tickets/{self.ticket.pk}/set-stage/", {"status": status, **extra}, format="json")

    def assign(self):
        response = self.client_.post(f"/api/tickets/{self.ticket.pk}/assign/", {"assigned_to": self.staff.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def diagnose(self):
        response = client_for(self.staff).post(f"/api/tickets/{self.ticket.pk}/diagnose/", {"note": "Screen cracked", "estimate_ok": True}, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def status(self):
        self.ticket.refresh_from_db()
        return self.ticket.status

    def test_nothing_moves_before_assignment(self):
        for target in ("Diagnosing", "In progress", "Ready for pickup"):
            response = self.stage(target)
            self.assertEqual(response.status_code, 400, target)
            self.assertEqual(response.json()["code"], "needs_assignment")
        self.assertEqual(self.client_.post(f"/api/tickets/{self.ticket.pk}/advance/").status_code, 400)
        self.assertEqual(self.status(), RepairTicket.RECEIVED)

    def test_the_super_admin_follows_the_same_order(self):
        response = self.stage("Ready for pickup", client=client_for(self.sa))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.status(), RepairTicket.RECEIVED)

    def test_invoice_cannot_be_raised_on_an_unassigned_job(self):
        self.assertEqual(self.client_.post(f"/api/tickets/{self.ticket.pk}/settle/").status_code, 400)
        self.assertFalse(Invoice.objects.filter(repair_ticket=self.ticket).exists())

    def test_ready_needs_work_in_progress_first(self):
        self.assign()
        self.diagnose()
        response = self.stage("Ready for pickup")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "work_not_started")

    def test_assigned_job_still_waits_for_the_staff_report(self):
        self.assign()
        self.assertEqual(self.stage("In progress").status_code, 400)
        self.assertEqual(self.status(), RepairTicket.RECEIVED)

    def test_paid_is_what_releases_the_device(self):
        self.assign()
        self.diagnose()
        self.assertEqual(self.stage("In progress").status_code, 200)
        self.assertEqual(self.stage("Ready for pickup").status_code, 200)
        self.assertEqual(self.client_.post(f"/api/tickets/{self.ticket.pk}/settle/").status_code, 200)
        self.assertEqual(self.status(), RepairTicket.READY)
        invoice = Invoice.objects.get(repair_ticket=self.ticket)
        self.assertEqual(self.client_.post(f"/api/invoices/{invoice.pk}/settle/", {"pay_method": "Cash"}, format="json").status_code, 200)
        self.assertEqual(self.status(), RepairTicket.DELIVERED)

    def test_moving_back_stays_allowed(self):
        self.assign()
        self.diagnose()
        self.stage("In progress")
        self.assertEqual(self.stage("Diagnosing").status_code, 200)


class ApprovalWhatsAppTests(Base):
    def setUp(self):
        super().setUp()
        self.client_ = client_for(self.admin)
        self.ticket = RepairTicket.objects.get(pk=self.book(self.admin).data["id"])

    def link(self):
        return self.client_.post(f"/api/tickets/{self.ticket.pk}/approval-link/").json()

    def send(self, url, client=None):
        return (client or self.client_).post(f"/api/tickets/{self.ticket.pk}/approval-link/send-whatsapp/", {"approval_url": url}, format="json")

    @mock.patch("repairs.services.send_whatsapp", return_value={"status": "sent", "provider_id": "wamid.1"})
    def test_booking_sends_the_link_and_reports_it(self, sender):
        response = self.book(self.admin)
        self.assertEqual(response.data["approval"]["whatsapp_delivery"]["status"], "sent")
        self.assertIn(response.data["approval"]["url"], sender.call_args.args[1])

    @mock.patch("repairs.services.send_whatsapp", return_value={"status": "sent", "provider_id": "wamid.2"})
    def test_link_goes_once_to_the_customer(self, sender):
        url = self.link()["approval_url"]
        self.assertEqual(self.send(url).status_code, 200)
        self.assertEqual(sender.call_args.args[0], self.party.phone)
        self.assertIn(url, sender.call_args.args[1])
        self.assertEqual(self.send(url).status_code, 409)
        self.assertEqual(sender.call_count, 1)

    @mock.patch("repairs.services.send_whatsapp", return_value={"status": "failed", "reason": "no"})
    def test_a_failed_send_can_be_retried(self, sender):
        url = self.link()["approval_url"]
        self.send(url)
        self.assertEqual(self.send(url).json()["whatsapp_delivery"]["status"], "failed")
        self.assertEqual(sender.call_count, 2)

    @mock.patch("repairs.services.send_whatsapp")
    def test_only_this_jobs_live_link_can_be_sent(self, sender):
        old = self.link()["approval_url"]
        self.link()
        self.assertEqual(self.send(old).status_code, 400)
        self.assertEqual(self.send("https://evil.test/anything-at-all-here").status_code, 400)
        sender.assert_not_called()

    def test_needs_approval_permission(self):
        url = self.link()["approval_url"]
        self.assertEqual(self.send(url, client=client_for(self.staff)).status_code, 403)

    def test_console_mode_says_nothing_was_sent(self):
        response = self.book(self.admin)
        self.assertEqual(response.data["approval"]["whatsapp_provider"], "console")
        self.assertEqual(response.data["approval"]["whatsapp_delivery"]["status"], "simulated")


class PortalEndsAtDeliveryTests(Base):
    def setUp(self):
        super().setUp()
        self.boss = make_user("boss2", ADMIN + ("invoices.view", "invoices.settle", "invoices.create"), stock_point=self.store)
        self.client_ = client_for(self.boss)
        self.party.email = "cust@example.test"
        self.party.save(update_fields=["email"])

    def job(self):
        ticket = RepairTicket.objects.get(pk=self.book(self.boss).data["id"])
        self.approve_current(ticket)
        give_out(ticket, self.staff)
        self.client_.post(f"/api/tickets/{ticket.pk}/set-stage/", {"status": "In progress"}, format="json")
        self.client_.post(f"/api/tickets/{ticket.pk}/set-stage/", {"status": "Ready for pickup"}, format="json")
        return ticket

    def deliver(self, ticket):
        self.client_.post(f"/api/tickets/{ticket.pk}/settle/")
        invoice = Invoice.objects.get(repair_ticket=ticket)
        self.client_.post(f"/api/invoices/{invoice.pk}/settle/", {"pay_method": "Cash"}, format="json")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, RepairTicket.DELIVERED)

    def session(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Portal {issue_portal_token(self.party)}")
        return client

    def test_link_lasts_as_long_as_the_job(self):
        self.job()
        invite, _ = create_portal_invite(self.party, self.boss)
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(days=10)):
            self.assertIsNone(invite_closed_code(invite))

    def test_portal_stays_24_hours_after_the_final_payment(self):
        ticket = self.job()
        invite, _ = create_portal_invite(self.party, self.boss)
        session = self.session()
        self.deliver(ticket)
        self.assertIsNone(invite_closed_code(invite))
        self.assertEqual(session.get("/api/portal/repairs/").json()["invoices"][0]["status"], "Paid")
        later = timezone.now() + timedelta(hours=24, minutes=1)
        self.assertEqual(invite_closed_code(invite, later), "invite_expired")
        RepairTicket.objects.filter(pk=ticket.pk).update(portal_until=timezone.now() - timedelta(minutes=1))
        response = session.get("/api/portal/me/")
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(response.json()["code"], "repair_access_ended")

    def test_paid_in_full_in_advance_closes_at_delivered(self):
        ticket = self.job()
        invite, _ = create_portal_invite(self.party, self.boss)
        RepairTicket.objects.filter(pk=ticket.pk).update(advance_paid=1500)
        self.assertEqual(self.client_.post(f"/api/tickets/{ticket.pk}/settle/").status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.portal_until), (RepairTicket.DELIVERED, None))
        self.assertEqual(invite_closed_code(invite), "invite_expired")

    def test_no_new_link_once_closed(self):
        ticket = self.job()
        self.deliver(ticket)
        RepairTicket.objects.filter(pk=ticket.pk).update(portal_until=None)
        with self.assertRaises(ValidationError):
            create_portal_invite(self.party, self.boss)

    def test_another_open_job_keeps_the_link(self):
        ticket = self.job()
        self.job()
        invite, _ = create_portal_invite(self.party, self.boss)
        self.deliver(ticket)
        self.assertIsNone(invite_closed_code(invite))

    def test_a_new_link_works_for_a_later_job(self):
        ticket = self.job()
        self.deliver(ticket)
        RepairTicket.objects.filter(pk=ticket.pk).update(portal_until=None)
        self.job()
        invite, _ = create_portal_invite(self.party, self.boss)
        self.assertEqual(self.client_.get(f"/api/portal/invite-status/{invite.token}/").status_code, 200)

    def rental_customer(self, status=Rental.CLOSED):
        Party.objects.filter(pk=self.party.pk).update(type=Party.RENTAL)
        self.party.refresh_from_db()
        Rental.objects.create(party=self.party, status=status, product_label="ThinkPad", monthly_fee=2000,
                              start=date(2024, 1, 1), last_payment=date(2024, 1, 1), tenure_months=6)

    def test_old_rental_history_does_not_block_a_repair_link(self):
        for status in (Rental.CLOSED, Rental.CANCELLED, Rental.ACTIVE):  # active but past its tenure: overdue
            with self.subTest(status=status):
                Rental.objects.filter(party=self.party).delete()
                self.rental_customer(status)
                ticket = self.job()
                invite, _ = create_portal_invite(self.party, self.boss)
                self.assertIsNone(invite_closed_code(invite))
                self.assertTrue(self.session().get("/api/portal/me/").json()["repair_only"])
                self.deliver(ticket)
                RepairTicket.objects.filter(party=self.party).update(portal_until=None)
                self.assertEqual(invite_closed_code(invite), "invite_expired")

    def test_running_rental_keeps_its_full_portal(self):
        self.rental_customer(Rental.ACTIVE)
        Rental.objects.filter(party=self.party).update(start=date.today(), last_payment=date.today())
        self.deliver(self.job())
        me = self.session().get("/api/portal/me/")
        self.assertEqual(me.status_code, 200)
        self.assertFalse(me.json()["repair_only"])

