"""What a renter sees in the portal: laptop status, money held, payment links and issues."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from parties.models import Party
from rentals.models import Rental, RentalIssue
from sales.models import Invoice, InvoiceItem, PaymentLink
from .test_portal_data import PortalDataTestBase
from .tests import ROOMY_RATES


class PortalRentalsTestBase(PortalDataTestBase):
    def setUp(self):
        super().setUp()
        self.party = self.make_party(Party.RENTAL, email="renter@example.test")
        self.rental = self.agreement(self.party, code="AGR-1")
        self.client_, _ = self.session(self.party)

    def agreement(self, party, code, status=Rental.ACTIVE):
        return Rental.objects.create(
            party=party, agreement_code=code, status=status, product_label="ThinkPad", monthly_fee=2000,
            start=date.today(), last_payment=date.today(), tenure_months=6,
        )

    def bill(self, code, status=Invoice.LINK_SENT, rental=None, **kinds):
        invoice = Invoice.objects.create(
            code=code, party=self.party, stock_point=self.shop, date=date.today(), status=status,
            due_date=date.today() + timedelta(days=7), source=Invoice.RENTAL, rental=rental or self.rental, **kinds,
        )
        InvoiceItem.objects.create(invoice=invoice, description="Rent", qty=1, price=2000)
        return invoice

    def link(self, invoice, url="https://rzp.io/l/abc", status=PaymentLink.SENT):
        staff = get_user_model().objects.create(username=f"staff-{invoice.pk}-{PaymentLink.objects.count()}")
        return PaymentLink.objects.create(
            invoice=invoice, phone="9876543210", upi_check=PaymentLink.UPI_STAFF_CONFIRMED, amount=2000,
            provider="razorpay", url=url, status=status, sent_by=staff,
        )

    def rentals(self):
        response = self.client_.get("/api/portal/rentals/")
        self.assertEqual(response.status_code, 200, response.content)
        return {row["agreement_code"]: row for row in response.json()}


class LaptopAndMoneyTests(PortalRentalsTestBase):
    def test_active_rental_shows_the_laptop_with_the_customer(self):
        self.assertEqual(self.rentals()["AGR-1"]["laptop_status"]["key"], "with_you")

    def test_deposit_and_advance_are_shown(self):
        self.bill("DEP-1", status=Invoice.PAID, is_deposit=True)
        self.bill("ADV-1", status=Invoice.PAID, is_advance=True)
        row = self.rentals()["AGR-1"]
        self.assertEqual((row["security_deposit"]["code"], row["security_deposit"]["amount"]), ("DEP-1", 2000))
        self.assertEqual(row["security_deposit"]["status"], Invoice.PAID)
        self.assertEqual(row["advance"]["code"], "ADV-1")

    def test_a_rental_without_them_shows_none(self):
        row = self.rentals()["AGR-1"]
        self.assertIsNone(row["security_deposit"])
        self.assertIsNone(row["advance"])

    def test_staff_only_fields_stay_hidden(self):
        self.assertFalse({"churn_score", "churn_band", "late_count", "tickets"} & set(self.rentals()["AGR-1"]))


class PaymentLinkTests(PortalRentalsTestBase):
    def test_due_rent_carries_the_link_staff_sent(self):
        self.link(self.bill("RENT-1"))
        due = self.rentals()["AGR-1"]["payments_due"]
        self.assertEqual([(d["code"], d["payment_url"]) for d in due], [("RENT-1", "https://rzp.io/l/abc")])

    def test_no_link_sent_yet(self):
        self.bill("RENT-1")
        self.assertIsNone(self.rentals()["AGR-1"]["payments_due"][0]["payment_url"])

    def test_paid_bills_have_no_link(self):
        self.link(self.bill("RENT-1", status=Invoice.PAID))
        self.assertEqual(self.rentals()["AGR-1"]["payments_due"], [])
        invoices = self.client_.get("/api/portal/invoices/").json()
        self.assertIsNone(invoices[0]["payment_url"])

    def test_cancelled_or_unsafe_links_are_never_given_out(self):
        invoice = self.bill("RENT-1")
        self.link(invoice, status=PaymentLink.CANCELLED)
        self.link(invoice, url="http://rzp.io/l/plain")
        self.assertIsNone(self.client_.get("/api/portal/invoices/").json()[0]["payment_url"])

    def test_invoice_list_stays_free_of_link_records(self):
        self.link(self.bill("RENT-1"))
        row = self.client_.get("/api/portal/invoices/").json()[0]
        self.assertEqual(row["payment_url"], "https://rzp.io/l/abc")
        self.assertNotIn("payment_links", row)


class IssueTests(PortalRentalsTestBase):
    def raise_issue(self, client=None, **extra):
        payload = {"rental": self.rental.pk, "title": "Battery drains fast", "description": "Lasts one hour.", **extra}
        return (client or self.client_).post("/api/portal/issues/", payload, format="json")

    def test_issue_reaches_the_staff_list(self):
        response = self.raise_issue()
        self.assertEqual(response.status_code, 201, response.content)
        issue = RentalIssue.objects.get()
        self.assertEqual((issue.rental, issue.status), (self.rental, RentalIssue.OPEN))
        self.rental.refresh_from_db()
        self.assertEqual(self.rental.tickets, 1)

    def test_customer_sees_their_issue_without_the_assignee(self):
        self.raise_issue()
        row = self.client_.get("/api/portal/issues/").json()[0]
        self.assertEqual((row["title"], row["status"], row["agreement_code"]), ("Battery drains fast", "Open", "AGR-1"))
        self.assertNotIn("assigned_to", row)

    def test_another_customers_rental_is_refused(self):
        other = self.make_party(Party.RENTAL, email="other@example.test")
        theirs = self.agreement(other, code="AGR-2")
        self.assertEqual(self.raise_issue(rental=theirs.pk).status_code, 400)
        self.assertFalse(RentalIssue.objects.exists())

    def test_customers_cannot_read_each_others_issues(self):
        self.raise_issue()
        other = self.make_party(Party.RENTAL, email="other@example.test")
        self.agreement(other, code="AGR-2")
        their_client, _ = self.session(other)
        self.assertEqual(their_client.get("/api/portal/issues/").json(), [])

    def test_customer_values_cannot_set_staff_fields(self):
        self.raise_issue(status="Resolved", assigned_to=1, party=999)
        self.assertEqual(RentalIssue.objects.get().status, RentalIssue.OPEN)
        self.assertIsNone(RentalIssue.objects.get().assigned_to)

    def test_closed_rental_is_refused(self):
        closed = self.agreement(self.party, code="AGR-3", status=Rental.CLOSED)
        self.assertEqual(self.raise_issue(rental=closed.pk).status_code, 400)

    def test_bad_input_is_refused(self):
        for extra in ({"title": "  "}, {"title": "x" * 141}, {"description": "x" * 2001}, {"rental": "abc"}):
            self.assertEqual(self.raise_issue(**extra).status_code, 400, extra)

    def test_signed_out_is_refused(self):
        self.assertIn(self.raise_issue(client=APIClient()).status_code, (401, 403))

    def test_issues_are_capped(self):
        with mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", {**ROOMY_RATES, "portal_issue": "1/hour"}):
            self.assertEqual(self.raise_issue().status_code, 201)
            self.assertEqual(self.raise_issue().status_code, 429)


class AgreementAndHistoryTests(PortalRentalsTestBase):
    def attach(self, rental):
        rental.signed_content_type = "application/pdf"
        rental.signed_agreement.save("signed.pdf", ContentFile(b"%PDF-1.4 signed"), save=False)
        rental.signed_uploaded_at = timezone.now()
        rental.save()

    def test_customer_downloads_their_signed_copy(self):
        self.attach(self.rental)
        self.assertIsNotNone(self.rentals()["AGR-1"]["signed_agreement_uploaded_at"])
        response = self.client_.get(f"/api/portal/rentals/{self.rental.pk}/signed-agreement/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"signed", b"".join(response.streaming_content))
        self.assertIn("AGR-1-signed.pdf", response["Content-Disposition"])

    def test_no_copy_on_file(self):
        self.assertIsNone(self.rentals()["AGR-1"]["signed_agreement_uploaded_at"])
        self.assertEqual(self.client_.get(f"/api/portal/rentals/{self.rental.pk}/signed-agreement/").status_code, 404)

    def test_another_customers_copy_is_refused(self):
        other = self.make_party(Party.RENTAL, email="other@example.test")
        theirs = self.agreement(other, code="AGR-2")
        self.attach(theirs)
        self.assertEqual(self.client_.get(f"/api/portal/rentals/{theirs.pk}/signed-agreement/").status_code, 404)

    def test_signed_out_is_refused(self):
        self.attach(self.rental)
        self.assertIn(APIClient().get(f"/api/portal/rentals/{self.rental.pk}/signed-agreement/").status_code, (401, 403))

    def test_history_lists_paid_invoices_only(self):
        self.bill("DEP-1", status=Invoice.PAID, is_deposit=True)
        rent = self.bill("RENT-1", status=Invoice.PAID)
        Invoice.objects.filter(pk=rent.pk).update(period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), paid_on=date.today(), pay_method="Cash")
        self.bill("RENT-2")
        history = self.rentals()["AGR-1"]["payment_history"]
        self.assertEqual({row["code"]: row["label"] for row in history}, {
            "DEP-1": "Security deposit", "RENT-1": "Rent 01 Jan 2026 to 31 Jan 2026"})

    def test_old_agreements_keep_their_history(self):
        old = self.agreement(self.party, code="AGR-OLD", status=Rental.CLOSED)
        self.bill("OLD-1", status=Invoice.PAID, rental=old)
        self.assertEqual([r["code"] for r in self.rentals()["AGR-OLD"]["payment_history"]], ["OLD-1"])
