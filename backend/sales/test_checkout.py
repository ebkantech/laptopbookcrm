"""Razorpay Standard Checkout -- the Test Mode only "Test UPI Payment" flow."""
import hashlib
import hmac
import os
from datetime import date
from unittest import mock

from django.test import TestCase

from catalog.models import Product, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from sales.models import Invoice, InvoiceItem, PaymentLink

SECRET = "test_secret"
TEST_ENV = {"PAYMENT_PROVIDER": "razorpay", "RAZORPAY_KEY_ID": "rzp_test_abc", "RAZORPAY_KEY_SECRET": SECRET,
            "UPI_LOOKUP_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"}


def sign(order_id, payment_id, secret=SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


@mock.patch.dict(os.environ, TEST_ENV)
class TestCheckoutTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="UPI Customer", type=Party.RETAIL, phone="+91 98765 43211", joined=date.today())
        product = Product.objects.create(model_name="Mouse", product_code="TEST-ACC-0001")
        self.variant = Variant.objects.create(product=product, code="TEST-SKU-0001", spec="Black", mrp=600, sell_price=500, cost=300)
        self.invoice = self.make_invoice("INV-CHK")
        self.user = make_user("sales-person", ["invoices.view", "payments.send_link"], stock_point=self.shop)
        self.client_ = client_for(self.user)
        self.url = f"/api/invoices/{self.invoice.id}"

    def make_invoice(self, code):
        invoice = Invoice.objects.create(code=code, party=self.party, stock_point=self.shop, date=date.today())
        InvoiceItem.objects.create(invoice=invoice, variant=self.variant, qty=2, price=500)  # Rs 1000
        return invoice

    def razorpay(self, order=None, payment=None):
        """A fake _razorpay_request answering for one order and one payment."""
        order = {"id": "order_1", "amount": 100000, "currency": "INR",
                 "notes": {"invoice": self.invoice.code, "invoice_id": str(self.invoice.pk), "purpose": "crm_test_checkout"},
                 **(order or {})}
        payment = {"id": "pay_1", "order_id": "order_1", "amount": 100000, "currency": "INR", "status": "captured",
                   "method": "upi", "acquirer_data": {"rrn": "412312341234"}, **(payment or {})}

        def fake(method, path, payload=None):
            if (method, path) == ("POST", "/orders"):
                return {"id": "order_1", "amount": payload["amount"], "currency": payload["currency"]}
            if (method, path) == ("GET", f"/orders/{order['id']}"):
                return order
            if (method, path) == ("GET", f"/payments/{payment['id']}"):
                return payment
            raise AssertionError(f"unexpected Razorpay call {method} {path}")
        return mock.patch("sales.payments._razorpay_request", side_effect=fake)

    def verify(self, order_id="order_1", payment_id="pay_1", signature=None, url=None, client=None):
        return (client or self.client_).post(f"{url or self.url}/test-checkout-verify/", {
            "razorpay_order_id": order_id, "razorpay_payment_id": payment_id,
            "razorpay_signature": signature if signature is not None else sign(order_id, payment_id),
        }, format="json")

    # -- availability and order creation ---------------------------------

    def test_config_offers_checkout_only_with_a_razorpay_test_key(self):
        self.assertTrue(self.client_.get("/api/invoices/test-checkout-config/").json()["available"])
        for env in ({"RAZORPAY_KEY_ID": "rzp_live_abc"}, {"RAZORPAY_KEY_ID": "bogus"}, {"PAYMENT_PROVIDER": "sandbox"}):
            with mock.patch.dict(os.environ, env):
                self.assertFalse(self.client_.get("/api/invoices/test-checkout-config/").json()["available"], env)

    def test_order_is_created_for_the_invoice_total(self):
        with self.razorpay() as rp:
            response = self.client_.post(f"{self.url}/test-checkout-order/", {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        method, path, payload = rp.call_args.args
        self.assertEqual((method, path, payload["amount"], payload["currency"]), ("POST", "/orders", 100000, "INR"))
        self.assertEqual(payload["notes"], {"invoice": "INV-CHK", "invoice_id": str(self.invoice.pk), "purpose": "crm_test_checkout"})
        self.assertTrue(payload["receipt"].startswith("INV-CHK-"))
        body = response.json()
        self.assertEqual((body["key_id"], body["order_id"], body["amount"]), ("rzp_test_abc", "order_1", 100000))
        self.assertEqual(body["prefill"]["contact"], "9876543211")
        self.assertNotIn(SECRET, response.content.decode())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)  # creating an order settles nothing

    def test_live_key_is_refused(self):
        with mock.patch.dict(os.environ, {"RAZORPAY_KEY_ID": "rzp_live_abc"}), self.razorpay() as rp:
            order = self.client_.post(f"{self.url}/test-checkout-order/", {}, format="json")
            verify = self.verify()
        self.assertEqual((order.status_code, verify.status_code), (403, 403))
        rp.assert_not_called()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)

    def test_no_order_for_a_paid_or_cancelled_invoice(self):
        for status in (Invoice.PAID, Invoice.CANCELLED):
            Invoice.objects.filter(pk=self.invoice.pk).update(status=status)
            with self.razorpay() as rp:
                self.assertEqual(self.client_.post(f"{self.url}/test-checkout-order/", {}, format="json").status_code, 400)
            rp.assert_not_called()

    def test_razorpay_error_creating_order_is_reported(self):
        from sales.payments import PaymentProviderError
        with mock.patch("sales.payments._razorpay_request", side_effect=PaymentProviderError("Razorpay error: bad")):
            response = self.client_.post(f"{self.url}/test-checkout-order/", {}, format="json")
        self.assertEqual((response.status_code, response.json()["detail"]), (502, "Razorpay error: bad"))

    # -- verification -------------------------------------------------------

    def test_captured_upi_payment_settles_the_invoice(self):
        PaymentLink.objects.create(invoice=self.invoice, phone="9876543211", upi_check="verified", amount=1000,
                                   provider="razorpay", provider_link_id="plink_open", sent_by=self.user)
        with self.razorpay():
            response = self.verify()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Invoice.PAID)
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.status, self.invoice.pay_method), (Invoice.PAID, "UPI"))
        self.assertEqual(self.invoice.payment_reference, "UPI RRN 412312341234 / pay_1")
        self.assertEqual(self.invoice.paid_on, date.today())
        self.assertIsNone(self.invoice.settled_by)
        self.assertEqual(PaymentLink.objects.get().status, PaymentLink.CANCELLED)  # the open link is moot

    def test_payment_posts_to_the_books(self):
        with self.razorpay(), mock.patch("sales.services.on_invoice_paid") as paid:
            self.assertEqual(self.verify().status_code, 200)
        paid.assert_called_once()
        self.assertEqual(paid.call_args.args[0].pk, self.invoice.pk)

    def test_non_upi_payment_is_not_recorded_as_upi(self):
        for method, recorded in (("card", "Card"), ("netbanking", "Bank transfer"), ("wallet", "Other")):
            invoice = self.make_invoice(f"INV-{method}")
            self.invoice = invoice
            with self.razorpay(payment={"id": f"pay_{method}", "method": method}):
                response = self.verify(payment_id=f"pay_{method}", url=f"/api/invoices/{invoice.id}")
            self.assertEqual(response.status_code, 200, response.content)
            invoice.refresh_from_db()
            self.assertEqual(invoice.pay_method, recorded)
            self.assertEqual(invoice.payment_reference, f"pay_{method}")
            self.assertNotIn("UPI", invoice.payment_reference)

    def test_invalid_signature_is_refused_without_asking_razorpay(self):
        for signature in ("nope", sign("order_1", "pay_1", secret="other"), sign("order_1", "pay_2")):
            with self.razorpay() as rp:
                response = self.verify(signature=signature)
            self.assertEqual(response.status_code, 400)
            rp.assert_not_called()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)

    def test_missing_or_malformed_ids_are_refused(self):
        for order_id, payment_id in (("", "pay_1"), ("order_1", ""), ("plink_1", "pay_1"), ("order_1", "x" * 50)):
            with self.razorpay() as rp:
                self.assertEqual(self.verify(order_id=order_id, payment_id=payment_id).status_code, 400)
            rp.assert_not_called()

    def test_payment_not_captured_is_not_settled(self):
        for status in ("authorized", "failed", "created"):
            with self.razorpay(payment={"status": status}):
                response = self.verify()
            self.assertEqual(response.status_code, 409)
            self.assertIn(status, response.json()["detail"])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)

    def test_duplicate_and_replayed_payment(self):
        with self.razorpay():
            self.assertEqual(self.verify().status_code, 200)
            replay = self.verify()
        self.assertEqual(replay.status_code, 409)
        # the same payment can't settle a second invoice either
        other = self.make_invoice("INV-OTHER")
        with self.razorpay(order={"notes": {"invoice_id": str(other.pk), "purpose": "crm_test_checkout"}}), \
                mock.patch("sales.services.on_invoice_paid") as paid:
            response = self.verify(url=f"/api/invoices/{other.id}")
        self.assertEqual(response.status_code, 409)
        paid.assert_not_called()
        other.refresh_from_db()
        self.assertEqual(other.status, Invoice.LINK_SENT)

    def test_payment_already_recorded_on_a_payment_link_is_refused(self):
        PaymentLink.objects.create(invoice=self.invoice, phone="9876543211", upi_check="verified", amount=1000,
                                   provider="razorpay", provider_link_id="plink_x", status=PaymentLink.PAID,
                                   provider_payment_id="pay_1", sent_by=self.user)
        with self.razorpay():
            self.assertEqual(self.verify().status_code, 409)

    def test_order_for_another_invoice_is_refused(self):
        other = self.make_invoice("INV-OTHER")
        with self.razorpay(order={"notes": {"invoice_id": str(other.pk), "purpose": "crm_test_checkout"}}):
            response = self.verify()
        self.assertEqual(response.status_code, 400)
        self.assertIn("wasn't created for this invoice", response.json()["detail"])
        # an order made elsewhere (no purpose note) is refused too
        with self.razorpay(order={"notes": {"invoice_id": str(self.invoice.pk)}}):
            self.assertEqual(self.verify().status_code, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)

    def test_payment_from_another_order_is_refused(self):
        with self.razorpay(payment={"order_id": "order_2"}):
            response = self.verify()
        self.assertEqual(response.status_code, 400)
        self.assertIn("doesn't belong to that order", response.json()["detail"])

    def test_wrong_amount_is_refused(self):
        for order, payment in (({"amount": 50000}, {}), ({}, {"amount": 50000}), ({}, {"currency": "USD"})):
            with self.razorpay(order=order, payment=payment):
                response = self.verify()
            self.assertEqual(response.status_code, 400, (order, payment))
        # an invoice revised after the order was created no longer matches it
        InvoiceItem.objects.filter(invoice=self.invoice).update(qty=3)
        with self.razorpay():
            self.assertEqual(self.verify().status_code, 400)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)

    def test_cancelled_invoice_is_not_revived(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.CANCELLED)
        with self.razorpay():
            self.assertEqual(self.verify().status_code, 409)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.CANCELLED)

    def test_razorpay_error_while_verifying_is_reported(self):
        from sales.payments import PaymentProviderError
        with mock.patch("sales.payments._razorpay_request", side_effect=PaymentProviderError("Couldn't reach Razorpay: x")):
            self.assertEqual(self.verify().status_code, 502)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)

    # -- permissions --------------------------------------------------------

    def test_permission_denial(self):
        viewer = client_for(make_user("viewer-only", ["invoices.view"], stock_point=self.shop))
        repair_user = make_user("repair-tech", ["invoices.view", "payments.send_link"], stock_point=self.shop)
        repair_user.role.slug = "repair_staff"
        repair_user.role.save()
        other_shop = StockPoint.objects.create(slug="other-shop", name="Other Shop", kind=StockPoint.SHOP)
        elsewhere = client_for(make_user("other-store", ["invoices.view", "payments.send_link"], stock_point=other_shop))
        with self.razorpay() as rp:
            self.assertEqual(viewer.get("/api/invoices/test-checkout-config/").status_code, 403)
            for client, expected in ((viewer, 403), (client_for(repair_user), 403), (elsewhere, 404)):
                self.assertEqual(client.post(f"{self.url}/test-checkout-order/", {}, format="json").status_code, expected)
                self.assertEqual(self.verify(client=client).status_code, expected)
        rp.assert_not_called()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)
