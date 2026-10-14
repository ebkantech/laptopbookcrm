"""Portal account types, per-customer data scoping, invoices and invoice PDFs."""
from datetime import date, timedelta
from unittest import mock

from django.core import mail
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from rentals.models import Rental
from sales.models import Invoice, InvoiceItem
from .access import rental_end_at
from .models import PortalInvite
from .tests import ROOMY_RATES, PortalTestBase


class PortalDataTestBase(PortalTestBase):
    def setUp(self):
        super().setUp()
        self.shop = StockPoint.objects.create(slug="portal-shop", name="Portal Shop", kind=StockPoint.SHOP)
        self.dealer = self.make_party(Party.DEALER, email="dealer@example.test")
        self.retail = self.make_party(Party.RETAIL, email="retail@example.test")

    def session(self, party):
        invite, otp = self.issue(party)
        response = self.verify(invite, otp)
        self.assertEqual(response.status_code, 200, response.content)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Portal {response.json()['portal_token']}")
        return client, response.json()

    def invoice(self, party, code, lines=(("Laptop", 1, 45000),)):
        inv = Invoice.objects.create(
            code=code, party=party, stock_point=self.shop, date=date.today(),
            due_date=date.today() + timedelta(days=7),
        )
        for description, qty, price in lines:
            InvoiceItem.objects.create(invoice=inv, description=description, qty=qty, price=price)
        return inv


class AccountTypeTests(PortalDataTestBase):
    def test_each_account_type_is_reported_exactly(self):
        # classification is a separate internal label and must never leak into `type`
        Party.objects.filter(pk=self.party.pk).update(customer_classification=Party.DEALER_CUSTOMER)
        self.make_rental(self.dealer)  # a dealer that also rents is still a Dealer
        for party, expected in ((self.party, "Rental"), (self.dealer, "Dealer"), (self.retail, "Retail")):
            client, verified = self.session(party)
            self.assertEqual(verified["party"]["type"], expected)
            me = client.get("/api/portal/me/").json()
            self.assertEqual(me["type"], expected)
            self.assertNotIn("customer_classification", me)
        dealer_me = self.session(self.dealer)[0].get("/api/portal/me/").json()
        self.assertIsNone(dealer_me["portal_access_ends_at"])

    def test_rental_profile_reports_entitlement_end(self):
        client, _ = self.session(self.party)
        me = client.get("/api/portal/me/").json()
        self.assertTrue(me["portal_access_ends_at"].startswith(rental_end_at(self.rental).date().isoformat()))

    def test_unknown_type_is_unknown_not_rental(self):
        odd = Party.objects.create(name="Odd", type="Corporate", phone="9000000009", email="odd@example.test", joined=date.today())
        client, verified = self.session(odd)
        self.assertEqual(verified["party"]["type"], "Unknown")
        self.assertEqual(client.get("/api/portal/me/").json()["type"], "Unknown")


class InvoiceAccessTests(PortalDataTestBase):
    def test_every_account_type_sees_only_its_own_invoices(self):
        own = {p.pk: self.invoice(p, f"INV-90{i}") for i, p in enumerate((self.party, self.dealer, self.retail))}
        for party in (self.party, self.dealer, self.retail):
            client, _ = self.session(party)
            listed = client.get("/api/portal/invoices/").json()
            self.assertEqual([row["id"] for row in listed], [own[party.pk].id])
            row = listed[0]
            self.assertEqual((row["total"], row["currency"], row["pdf_available"]), (45000, "INR", True))
            self.assertEqual(row["due_date"], own[party.pk].due_date.isoformat())
            self.assertFalse({"payment_links", "cancel_reason", "settled_by_name", "party"} & set(row))
            detail = client.get(f"/api/portal/invoices/{own[party.pk].id}/")
            self.assertEqual((detail.status_code, detail.json()["code"]), (200, own[party.pk].code))

    def test_another_customers_invoice_is_indistinguishable_from_a_missing_one(self):
        theirs = self.invoice(self.dealer, "INV-9100")
        client, _ = self.session(self.retail)
        missing_id = Invoice.objects.order_by("-id").first().id + 999
        for path in ("", "pdf/", "download/"):
            accept = "application/pdf" if path else "application/json"
            foreign = client.get(f"/api/portal/invoices/{theirs.id}/{path}", HTTP_ACCEPT=accept)
            missing = client.get(f"/api/portal/invoices/{missing_id}/{path}", HTTP_ACCEPT=accept)
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), missing.json())
            self.assertNotIn(b"%PDF", foreign.content)

    def test_pdf_download_is_a_real_pdf_with_a_safe_filename(self):
        invoice = self.invoice(self.dealer, 'INV-91"0/1', lines=(("Dell Latitude 5420", 2, 30000), ("Charger", 1, 1500)))
        client, _ = self.session(self.dealer)
        for path in ("pdf/", "download/"):
            response = client.get(f"/api/portal/invoices/{invoice.id}/{path}", HTTP_ACCEPT="application/pdf")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertEqual(response["Content-Disposition"], 'attachment; filename="Invoice-INV-91-0-1.pdf"')
            self.assertEqual(response["Cache-Control"], "no-store, private")
            self.assertTrue(response.content.startswith(b"%PDF"))

    def test_invoice_without_lines_has_no_pdf(self):
        empty = self.invoice(self.retail, "INV-9200", lines=())
        client, _ = self.session(self.retail)
        self.assertFalse(client.get("/api/portal/invoices/").json()[0]["pdf_available"])
        response = client.get(f"/api/portal/invoices/{empty.id}/pdf/", HTTP_ACCEPT="application/pdf")
        self.assertEqual((response.status_code, response.json()["code"]), (404, "pdf_unavailable"))

    def test_no_session_no_invoices(self):
        invoice = self.invoice(self.retail, "INV-9300")
        anonymous = APIClient()
        for path in ("/api/portal/invoices/", f"/api/portal/invoices/{invoice.id}/", f"/api/portal/invoices/{invoice.id}/pdf/"):
            self.assertEqual(anonymous.get(path).status_code, 403)
        staff = client_for(make_user("staff-no-portal", ["parties.view"]))  # a staff JWT is not a portal session
        self.assertEqual(staff.get(f"/api/portal/invoices/{invoice.id}/pdf/").status_code, 403)

    def test_pdf_generation_is_throttled_per_customer(self):
        invoice = self.invoice(self.retail, "INV-9400")
        client, _ = self.session(self.retail)
        with mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", {**ROOMY_RATES, "portal_pdf": "1/hour"}):
            self.assertEqual(client.get(f"/api/portal/invoices/{invoice.id}/pdf/").status_code, 200)
            self.assertEqual(client.get(f"/api/portal/invoices/{invoice.id}/pdf/").status_code, 429)


class RentalEntitlementTests(PortalDataTestBase):
    def test_rental_data_during_entitlement(self):
        Rental.objects.create(
            party=self.party, product_label="Draft", monthly_fee=1, start=date.today(), tenure_months=1,
            last_payment=date.today(), status=Rental.DRAFT,
        )
        self.make_rental(self.dealer)  # someone else's agreement
        client, _ = self.session(self.party)
        rentals = client.get("/api/portal/rentals/").json()
        self.assertEqual([r["id"] for r in rentals], [self.rental.id])
        self.assertEqual(rentals[0]["status"], Rental.ACTIVE)
        self.assertEqual(rentals[0]["end_date"], (rental_end_at(self.rental).date() - timedelta(days=1)).isoformat())
        self.assertNotIn("churn_score", rentals[0])

    def test_ended_entitlement_blocks_every_endpoint_including_downloads(self):
        invoice = self.invoice(self.party, "INV-9500")
        client, _ = self.session(self.party)
        self.assertEqual(client.get(f"/api/portal/invoices/{invoice.id}/pdf/").status_code, 200)
        end = rental_end_at(self.rental)
        with mock.patch("django.utils.timezone.now", return_value=end):
            for path in ("/api/portal/me/", "/api/portal/invoices/", f"/api/portal/invoices/{invoice.id}/",
                         f"/api/portal/invoices/{invoice.id}/pdf/", "/api/portal/rentals/"):
                response = client.get(path)
                self.assertEqual((response.status_code, response.json()["code"]), (403, "rental_access_ended"), path)

    def test_dealer_and_retail_are_never_cut_by_rental_rules(self):
        for party in (self.dealer, self.retail):
            Rental.objects.create(
                party=party, product_label="Old", monthly_fee=1, start=date.today() - timedelta(days=400),
                tenure_months=1, last_payment=date.today(), status=Rental.CLOSED,
            )
            client, _ = self.session(party)
            self.assertEqual(client.get("/api/portal/me/").status_code, 200)
            self.assertEqual(client.get("/api/portal/invoices/").status_code, 200)


class InviteStatusAndResendTests(PortalDataTestBase):
    def test_status_is_read_only(self):
        invite, otp = self.issue()
        before = PortalInvite.objects.get(pk=invite.pk)
        sent = len(mail.outbox)
        for _ in range(3):
            body = self.status(invite).json()
        after = PortalInvite.objects.get(pk=invite.pk)
        self.assertEqual(len(mail.outbox), sent)
        self.assertEqual(
            (after.otp_digest, after.otp_issued_at, after.otp_expires_at, after.expires_at, after.failed_attempts),
            (before.otp_digest, before.otp_issued_at, before.otp_expires_at, before.expires_at, before.failed_attempts),
        )
        self.assertEqual(body["otp_attempts_remaining"], 5)
        self.assertFalse({"otp", "otp_digest", "token", "portal_token", "email"} & set(body))
        self.assertEqual(self.verify(invite, otp).status_code, 200)  # the original code still works

    def test_concurrent_resend_cannot_leave_two_valid_codes(self):
        invite, _ = self.issue()
        self.skip_cooldown(invite)

        def racing_send(to, subject, body):
            # another request swaps the code while this one is emailing
            PortalInvite.objects.filter(pk=invite.pk).update(otp_digest="someone-else")
            return {"status": "sent"}

        with mock.patch("portal.services.send_email", side_effect=racing_send):
            response = self.resend(invite)
        self.assertEqual((response.status_code, response.json()["code"]), (409, "resend_conflict"))
        self.assertEqual(PortalInvite.objects.get(pk=invite.pk).otp_digest, "someone-else")

    def test_staff_get_the_real_link_policy(self):
        staff = client_for(make_user("manager", ["parties.view", "parties.manage"]))
        rental = staff.post(f"/api/parties/{self.party.id}/portal-invite/").json()
        self.assertEqual((rental["party_type"], rental["link_policy"]), ("Rental", "rental_tenure"))
        self.assertTrue(rental["invite_expires_at"].startswith(rental_end_at(self.rental).date().isoformat()))
        dealer = staff.post(f"/api/parties/{self.dealer.id}/portal-invite/").json()
        self.assertEqual((dealer["party_type"], dealer["link_policy"], dealer["otp_ttl_minutes"]), ("Dealer", "24_hours", 30))

    def test_customer_without_email_cannot_be_invited(self):
        no_email = self.make_party(Party.RETAIL, email="")
        staff = client_for(make_user("manager", ["parties.view", "parties.manage"]))
        response = staff.post(f"/api/parties/{no_email.id}/portal-invite/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json()["detail"])
        self.assertFalse(PortalInvite.objects.filter(party=no_email).exists())
