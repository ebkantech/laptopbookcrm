from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile

from django.utils import timezone
from rest_framework.test import APITestCase

from accounting.models import CashEntry
from catalog.models import StockPoint
from crmbook_backend.testing import client_for, complete_handover, make_user, verify_kyc
from parties.models import Party, PartyIdDocument
from portal.access import rental_access_ends_at
from reports.profit_loss import raw_figures
from sales.models import Invoice

from . import onboarding
from .billing import RentBillingError, next_billing_period, raise_rent_invoice, send_due_rent_invoices
from .models import Rental, RentalAsset, add_months

VALID_AADHAAR = "234123412346"
PERMS = ("rentals.view", "rentals.manage", "rentals.approve", "invoices.view", "invoices.create", "invoices.settle", "invoices.refund",
         "parties.view", "parties.manage")
PDF = b"%PDF-1.4 signed copy"


class Base(APITestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="main", name="Main", kind=StockPoint.SHOP)
        self.other_shop = StockPoint.objects.create(slug="other", name="Other", kind=StockPoint.SHOP)
        self.user = make_user("staff", perms=PERMS, stock_point=self.shop)
        self.client = client_for(self.user)
        self.party = Party.objects.create(name="Asha Rao", type=Party.RENTAL, phone="9876543210", email="a@example.com",
                                          city="Pune", joined=date(2026, 1, 1))
        self.asset = self._asset("A1")
        verify_kyc(self.party, self.user)

    def _asset(self, tag, shop=None):
        return RentalAsset.objects.create(asset_tag=tag, serial_number=f"SN-{tag}", brand="Dell", model_name="5420",
                                          source_stock_point=shop or self.shop)

    def create(self, party=None, assets=None, fee=2000, **extra):
        payload = {"party": (party or self.party).pk, "start": timezone.localdate().isoformat(), "tenure_months": 6,
                   "payment_interval_months": 1, "lines": [{"asset_id": a.pk, "monthly_fee": fee} for a in (assets or [self.asset])], **extra}
        response = self.client.post("/api/rentals/create-agreement/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return Rental.objects.get(pk=response.json()["id"])

    def pay(self, invoice):
        response = self.client.post(f"/api/invoices/{invoice.pk}/settle/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def record_id(self, id_type, number, party=None):
        return self.client.post("/api/party-ids/", {"party": (party or self.party).pk, "id_type": id_type, "number": number, "consent": True})

    def verified(self, id_type, number, party=None):
        response = self.record_id(id_type, number, party)
        self.assertEqual(response.status_code, 201, response.content)
        checked = self.client.post(f"/api/party-ids/{response.json()['id']}/verify/", {"outcome": "verified"}, format="json")
        self.assertEqual(checked.status_code, 200, checked.content)

    def card(self, rental):
        return self.client.get(f"/api/rentals/{rental.pk}/").json()["onboarding"]


class InvoiceTests(Base):
    def test_agreement_raises_one_month_deposit_and_advance(self):
        rental = self.create(assets=[self.asset, self._asset("A2")])
        deposit, advance = onboarding.deposit_invoice(rental), onboarding.advance_invoice(rental)
        self.assertEqual((deposit.total, advance.total), (4000, 4000))
        self.assertEqual(deposit.stock_point, self.shop)
        self.assertIn("Security deposit", self.client.get(f"/api/invoices/{deposit.pk}/").json()["reference"])
        self.assertIn("Advance rent", self.client.get(f"/api/invoices/{advance.pk}/").json()["reference"])

    def test_advance_counts_as_month_one_and_billing_starts_at_month_two(self):
        rental = self.create()
        self.pay(onboarding.advance_invoice(rental))
        rental.refresh_from_db()
        self.assertEqual(rental.months_paid, 1)
        self.assertEqual(rental.late_count, 0)
        self.assertEqual(next_billing_period(rental)[0], add_months(rental.start, 1))

    def test_deposit_never_counts_as_rent(self):
        rental = self.create()
        before = next_billing_period(rental)
        self.pay(onboarding.deposit_invoice(rental))
        rental.refresh_from_db()
        self.assertEqual(rental.months_paid, 0)
        self.assertEqual(next_billing_period(rental), before)
        self.assertEqual([r["code"] for r in self.client.get(f"/api/rentals/{rental.pk}/").json()["rent_invoices"]],
                         [onboarding.advance_invoice(rental).code])

    def test_deposit_is_in_the_cash_book_but_not_revenue(self):
        rental = self.create()
        deposit = onboarding.deposit_invoice(rental)
        self.pay(deposit)
        self.assertTrue(CashEntry.objects.filter(invoice=deposit, amount=2000).exists())
        today = timezone.localdate()
        figures = raw_figures([self.shop.pk], today, today)[self.shop.pk]
        self.assertEqual(figures["billed"][Invoice.RENTAL], 0)
        party = self.client.get(f"/api/parties/{self.party.pk}/").json()
        self.assertEqual(party["total_spent"], 2000)  # the unpaid advance, not the deposit

    def test_deposit_can_be_refunded_without_touching_rent_or_revenue(self):
        rental = self.create()
        deposit = onboarding.deposit_invoice(rental)
        self.pay(deposit)
        response = self.client.post(f"/api/invoices/{deposit.pk}/refund/", {"method": "Cash", "reason": "Agreement ended", "amount": 2000}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, Invoice.REFUNDED)
        today = timezone.localdate()
        self.assertEqual(raw_figures([self.shop.pk], today, today)[self.shop.pk]["refunds"][Invoice.RENTAL], 0)

    def test_renewal_keeps_the_deposit_and_charges_only_the_advance(self):
        first = self.create()
        Rental.objects.filter(pk=first.pk).update(status=Rental.CLOSED)
        RentalAsset.objects.filter(pk=self.asset.pk).update(status=RentalAsset.AVAILABLE)
        renewed = self.create(renews=first.pk)
        self.assertIsNone(onboarding.deposit_invoice(renewed))
        self.assertIsNotNone(onboarding.advance_invoice(renewed))
        self.assertFalse(self.card(renewed)["deposit_required"])

    def test_rent_change_updates_unpaid_invoices(self):
        rental = self.create()
        rental.lines.update(monthly_fee=3000)
        onboarding.sync_amounts(rental)
        self.assertEqual(onboarding.deposit_invoice(rental).total, 3000)
        self.assertEqual(onboarding.advance_invoice(rental).total, 3000)

    def test_older_agreements_are_untouched(self):
        rental = Rental.objects.create(party=self.party, product_label="Old", monthly_fee=1000, start=date(2026, 1, 1),
                                       tenure_months=6, last_payment=date(2026, 1, 1), status=Rental.DRAFT)
        self.assertEqual(onboarding.status(rental), {"required": False})
        onboarding.require_ready(rental)


class OrderTests(Base):
    def link(self, rental):
        return self.client.post(f"/api/rentals/{rental.pk}/approval-link/")

    def approve(self, rental):
        return self.client.post(f"/api/rentals/{rental.pk}/approve-on-behalf/", {"reason": "Signed in store"}, format="json")

    def checkout(self, rental):
        return self.client.post(f"/api/rentals/{rental.pk}/checkout/")

    def pay_both(self, rental):
        self.pay(onboarding.deposit_invoice(rental))
        self.pay(onboarding.advance_invoice(rental))

    def test_agreement_cannot_be_created_before_kyc(self):
        new = Party.objects.create(name="New", type=Party.RENTAL, phone="9000000001", joined=date(2026, 1, 1))
        payload = {"party": new.pk, "start": timezone.localdate().isoformat(), "tenure_months": 6, "payment_interval_months": 1,
                   "lines": [{"asset_id": self.asset.pk, "monthly_fee": 2000}]}
        response = self.client.post("/api/rentals/create-agreement/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("KYC", response.json()["detail"])
        self.assertFalse(Rental.objects.exists())
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, RentalAsset.AVAILABLE)

    def test_kyc_can_be_done_before_any_agreement_and_recorded_needs_verifying(self):
        new = Party.objects.create(name="New", type=Party.RENTAL, phone="9000000001", joined=date(2026, 1, 1))
        self.assertEqual(self.record_id("pan", "ABCPE1234F", party=new).status_code, 201)
        self.record_id("aadhaar", VALID_AADHAAR, party=new)
        self.assertIn("Verify the customer's PAN", " ".join(onboarding.id_problems(new)))

    def test_business_needs_pan_only(self):
        company = Party.objects.create(name="Acme", type=Party.RENTAL, phone="9000000000", joined=date(2026, 1, 1),
                                       customer_classification=Party.BUSINESS)
        self.verified("pan", "ABCCE1234F", party=company)
        self.assertEqual(onboarding.id_problems(company), [])
        self.create(party=company)

    def test_invalid_pan_is_refused(self):
        self.assertEqual(self.record_id("pan", "ABCDE12345").status_code, 400)
        self.assertEqual(self.record_id("pan", "ABCXE1234F").status_code, 400)

    def test_approval_comes_before_payment_and_keeps_the_device_reserved(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.assertEqual(self.link(rental).status_code, 200)
        self.assertEqual(self.approve(rental).status_code, 200)
        rental.refresh_from_db(), self.asset.refresh_from_db()
        self.assertEqual((rental.status, self.asset.status), (Rental.APPROVED, RentalAsset.RESERVED))
        self.assertTrue(self.card(rental)["waiting_for_handover"])

    def test_failed_id_stops_the_approval_link(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        PartyIdDocument.objects.filter(party=self.party, id_type="pan").update(status=PartyIdDocument.FAILED)
        self.assertIn("PAN", self.link(rental).json()["detail"])
        self.assertEqual(self.approve(rental).status_code, 400)

    def test_checkout_needs_approval_and_both_payments(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.assertEqual(self.checkout(rental).status_code, 400)  # not approved
        self.approve(rental)
        self.assertIn("security deposit", self.checkout(rental).json()["detail"])
        self.pay(onboarding.deposit_invoice(rental))
        self.assertIn("advance", self.checkout(rental).json()["detail"])
        self.pay(onboarding.advance_invoice(rental))
        rental.refresh_from_db()
        self.assertEqual(rental.status, Rental.APPROVED)  # paying alone doesn't hand the device over
        self.assertTrue(self.card(rental)["ready_for_checkout"])

    def test_checkout_makes_it_live(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.approve(rental)
        self.pay_both(rental)
        response = self.checkout(rental)
        self.assertEqual(response.status_code, 200, response.content)
        rental.refresh_from_db(), self.asset.refresh_from_db()
        self.assertEqual((rental.status, self.asset.status, rental.months_paid), (Rental.ACTIVE, RentalAsset.RENTED, 1))
        self.assertEqual(rental.checked_out_by, self.user)
        self.assertTrue(rental.events.filter(event_type="device_checked_out").exists())
        self.assertEqual(self.checkout(rental).status_code, 400)  # only once

    def test_viewer_cannot_check_out(self):
        rental = self.create()
        viewer = client_for(make_user("viewer", perms=("rentals.view",), stock_point=self.shop))
        self.assertEqual(viewer.post(f"/api/rentals/{rental.pk}/checkout/").status_code, 403)

    def test_portal_opens_once_approved_and_paid_before_checkout(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.approve(rental)
        self.assertIsNone(rental_access_ends_at(self.party))
        self.pay_both(rental)
        self.assertIsNotNone(rental_access_ends_at(self.party))

    def test_laptop_status_follows_the_agreement(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.assertEqual(onboarding.laptop_status(rental)["key"], "preparing")
        self.approve(rental)
        self.pay_both(rental)
        rental.refresh_from_db()
        self.assertEqual(onboarding.laptop_status(rental)["key"], "ready")
        self.checkout(rental)
        rental.refresh_from_db()
        self.assertEqual(onboarding.laptop_status(rental)["key"], "with_you")

    def test_no_rent_is_billed_before_checkout(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.approve(rental)
        self.pay_both(rental)
        rental.refresh_from_db()
        with self.assertRaises(RentBillingError):
            raise_rent_invoice(rental, stock_point=self.shop)
        self.assertEqual(send_due_rent_invoices(today=add_months(rental.start, 1))["raised"], [])

    def test_a_cancelled_invoice_can_be_raised_again(self):
        rental = self.create()
        deposit = onboarding.deposit_invoice(rental)
        self.client.post(f"/api/invoices/{deposit.pk}/cancel/", {"reason": "Mistake"}, format="json")
        self.assertIn("cancelled", " ".join(self.card(rental)["blocking"]))
        self.client.post(f"/api/rentals/{rental.pk}/raise-onboarding/")
        self.assertNotEqual(onboarding.deposit_invoice(rental).pk, deposit.pk)
        self.assertEqual(rental.invoices.filter(is_advance=True).count(), 1)

    def test_cancelling_the_agreement_cancels_unpaid_invoices_but_keeps_paid_ones(self):
        rental = self.create()
        deposit, advance = onboarding.deposit_invoice(rental), onboarding.advance_invoice(rental)
        self.pay(deposit)
        response = self.client.post(f"/api/rentals/{rental.pk}/cancel/", {"reason": "Customer left"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        deposit.refresh_from_db(), advance.refresh_from_db()
        self.assertEqual((deposit.status, advance.status), (Invoice.PAID, Invoice.CANCELLED))

    def test_closing_an_approved_rental_before_checkout_frees_the_device(self):
        rental = self.create()
        complete_handover(rental.lines.first(), self.user)
        self.approve(rental)
        self.client.post(f"/api/rentals/{rental.pk}/close/", {"reason": "Customer changed their mind"}, format="json")
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, RentalAsset.AVAILABLE)
        self.assertEqual(onboarding.deposit_invoice(rental), None)


class HandoverLockTests(Base):
    def test_new_agreement_waits_for_handover_and_stays_a_draft(self):
        rental = self.create()
        data = self.client.get(f"/api/rentals/{rental.pk}/").json()
        self.assertTrue(data["onboarding"]["waiting_for_handover"])
        self.assertEqual(data["status"], "draft")

    def test_device_details_can_be_recorded_before_payment(self):
        rental = self.create()
        response = self.client.patch(f"/api/rental-lines/{rental.lines.first().pk}/handover/", {"condition_notes": "Good"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_failed_id_locks_device_details(self):
        rental = self.create()
        PartyIdDocument.objects.filter(party=self.party, id_type="pan").update(status=PartyIdDocument.FAILED)
        response = self.client.patch(f"/api/rental-lines/{rental.lines.first().pk}/handover/", {"condition_notes": "Good"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Waiting for handover", response.json()["detail"])

    def test_older_agreements_keep_working(self):
        rental = Rental.objects.create(party=self.party, product_label="Old", monthly_fee=1000, start=date(2026, 1, 1),
                                       tenure_months=6, last_payment=date(2026, 1, 1), status=Rental.DRAFT)
        self.assertIsNone(onboarding.handover_locked_message(rental))


class AgreementFileTests(Base):
    def test_pdf_downloads(self):
        response = self.client.get(f"/api/rentals/{self.create().pk}/agreement-pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_signed_copy_upload_and_download(self):
        rental = self.create()
        upload = SimpleUploadedFile("signed.pdf", PDF, content_type="application/pdf")
        response = self.client.post(f"/api/rentals/{rental.pk}/signed-agreement/", {"file": upload})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["signed_agreement_info"]["name"], "signed.pdf")
        got = self.client.get(f"/api/rentals/{rental.pk}/signed-agreement/file/")
        self.assertEqual(b"".join(got.streaming_content), PDF)
        self.assertTrue(rental.events.filter(event_type="signed_agreement_uploaded").exists())

    def test_only_pdf_or_image_files(self):
        rental = self.create()
        bad = SimpleUploadedFile("signed.pdf", b"MZ not a pdf", content_type="application/pdf")
        self.assertEqual(self.client.post(f"/api/rentals/{rental.pk}/signed-agreement/", {"file": bad}).status_code, 400)

    def test_viewer_cannot_upload_and_other_store_cannot_read(self):
        rental = self.create()
        viewer = client_for(make_user("viewer", perms=("rentals.view",), stock_point=self.shop))
        upload = SimpleUploadedFile("signed.pdf", PDF, content_type="application/pdf")
        self.assertEqual(viewer.post(f"/api/rentals/{rental.pk}/signed-agreement/", {"file": upload}).status_code, 403)
        outsider = client_for(make_user("outsider", perms=PERMS, stock_point=self.other_shop))
        self.assertEqual(outsider.get(f"/api/rentals/{rental.pk}/agreement-pdf/").status_code, 404)
