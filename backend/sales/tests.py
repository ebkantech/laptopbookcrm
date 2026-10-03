import hashlib
import hmac
import json
import os
from datetime import date
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Message, Party
from sales.models import Invoice, InvoiceItem, PaymentLink


class InvoiceApiTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Test Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        product = Product.objects.create(brand="HP", model_name="EliteBook 840", product_code="TEST-LAP-0001")
        self.variant = Variant.objects.create(
            product=product, code="TEST-SKU-0001", spec="i5 / 8GB", mrp=40000, sell_price=35000, cost=30000
        )
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=10)
        self.seller = client_for(make_user("seller", ["invoices.view", "invoices.create", "invoices.settle"]))

    def create_invoice(self, client=None, qty=2, price=35000):
        return (client or self.seller).post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "items": [{"variant": self.variant.id, "qty": qty, "price": price}],
        }, format="json")

    def test_create_invoice_generates_code_computes_total_and_decrements_stock(self):
        response = self.create_invoice(qty=3)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["code"].startswith("INV-"))
        self.assertEqual(body["total"], 3 * 35000)
        self.assertEqual(body["status"], Invoice.LINK_SENT)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 7)

    def test_invoice_needs_at_least_one_item(self):
        response = self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(), "items": [],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.json())

    def test_settle_records_how_and_when_it_was_paid(self):
        invoice_id = self.create_invoice().json()["id"]
        response = self.seller.post(f"/api/invoices/{invoice_id}/settle/", {
            "pay_method": "UPI", "payment_reference": "UTR 412345678901", "paid_on": "2026-01-05",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["settled_by_name"], "seller")
        invoice = Invoice.objects.get(id=invoice_id)
        self.assertEqual(
            (invoice.status, invoice.pay_method, invoice.payment_reference, invoice.paid_on.isoformat()),
            (Invoice.PAID, "UPI", "UTR 412345678901", "2026-01-05"),
        )
        # can't be settled twice
        again = self.seller.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_settle_validation(self):
        invoice_id = self.create_invoice().json()["id"]
        url = f"/api/invoices/{invoice_id}/settle/"
        self.assertEqual(self.seller.post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.seller.post(url, {"pay_method": "Bitcoin"}, format="json").status_code, 400)
        # non-cash payments need a reference to trace them
        self.assertEqual(self.seller.post(url, {"pay_method": "UPI"}, format="json").status_code, 400)
        self.assertEqual(self.seller.post(url, {"pay_method": "Cash", "paid_on": "2999-01-01"}, format="json").status_code, 400)
        # cash needs no reference; paid_on defaults to today
        cash = self.seller.post(url, {"pay_method": "Cash"}, format="json")
        self.assertEqual(cash.status_code, 200)
        self.assertEqual(cash.json()["paid_on"], date.today().isoformat())

    def test_payment_fields_cannot_be_set_on_create(self):
        response = self.seller.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.shop.id, "date": date.today().isoformat(),
            "payment_reference": "fake", "items": [{"variant": self.variant.id, "qty": 1, "price": 1}],
        }, format="json")
        self.assertEqual(response.json()["payment_reference"], "")

    def test_print_data(self):
        self.shop.address = "12 Main Road, Karol Bagh, New Delhi"
        self.shop.gstin = "07ABCDE1234F1Z5"
        self.shop.save()
        self.variant.product.hsn = "84713010"
        self.variant.product.save()
        invoice_id = self.create_invoice(qty=2).json()["id"]

        data = self.seller.get(f"/api/invoices/{invoice_id}/print-data/").json()
        self.assertEqual(data["seller"]["branch"], "Test Shop")
        self.assertEqual(data["seller"]["address"], "12 Main Road, Karol Bagh, New Delhi")
        self.assertEqual(data["seller"]["gstin"], "07ABCDE1234F1Z5")
        self.assertEqual(data["buyer"]["name"], "Test Customer")
        self.assertEqual(
            {k: data["items"][0][k] for k in ("n", "hsn", "qty", "rate", "amount")},
            {"n": 1, "hsn": "84713010", "qty": 2, "rate": 35000, "amount": 70000},
        )
        self.assertEqual((data["total_qty"], data["total"]), (2, 70000))
        self.assertEqual(client_for(make_user("no-invoices")).get(f"/api/invoices/{invoice_id}/print-data/").status_code, 403)

    def test_list_filters_by_status_and_party(self):
        paid = Invoice.objects.create(code="INV-P", party=self.party, stock_point=self.shop, date=date.today(), status=Invoice.PAID)
        InvoiceItem.objects.create(invoice=paid, variant=self.variant, qty=1, price=1)
        other = Party.objects.create(name="Other", type=Party.RETAIL, phone="9876500000", joined=date.today())
        Invoice.objects.create(code="INV-O", party=other, stock_point=self.shop, date=date.today(), status=Invoice.OVERDUE)

        codes = lambda r: sorted(i["code"] for i in results(r))
        self.assertEqual(codes(self.seller.get("/api/invoices/", {"status": Invoice.PAID})), ["INV-P"])
        self.assertEqual(codes(self.seller.get("/api/invoices/", {"party": other.id})), ["INV-O"])

    def test_permissions(self):
        viewer = client_for(make_user("viewer", ["invoices.view"]))
        self.assertEqual(viewer.get("/api/invoices/").status_code, 200)
        self.assertEqual(self.create_invoice(client=viewer).status_code, 403)

        invoice_id = self.create_invoice().json()["id"]
        self.assertEqual(viewer.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash"}, format="json").status_code, 403)

        nobody = client_for(make_user("nobody"))
        self.assertEqual(nobody.get("/api/invoices/").status_code, 403)


@mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "sandbox", "UPI_LOOKUP_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"})
class UpiPaymentLinkTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="test-shop", name="Test Shop", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="UPI Customer", type=Party.RETAIL, phone="+91 98765 43211", joined=date.today())
        product = Product.objects.create(model_name="Mouse", product_code="TEST-ACC-0001")
        variant = Variant.objects.create(product=product, code="TEST-SKU-0001", spec="Black", mrp=600, sell_price=500, cost=300)
        self.invoice = Invoice.objects.create(code="INV-UPI", party=self.party, stock_point=self.shop, date=date.today())
        InvoiceItem.objects.create(invoice=self.invoice, variant=variant, qty=2, price=500)
        self.sender_user = make_user("sales-person", ["invoices.view", "invoices.settle", "payments.send_link"])
        self.sender_user.first_name, self.sender_user.last_name = "Naina", "Joshi"
        self.sender_user.save()
        self.sender = client_for(self.sender_user)
        self.url = f"/api/invoices/{self.invoice.id}"

    def test_check_uses_customer_number_by_default(self):
        body = self.sender.post(f"{self.url}/upi-check/", {}, format="json").json()
        self.assertEqual((body["phone"], body["status"], body["is_customer_number"]), ("9876543211", "linked", True))

    def test_number_without_upi_is_refused_and_another_number_works(self):
        check = self.sender.post(f"{self.url}/upi-check/", {"phone": "9876543210"}, format="json").json()
        self.assertEqual(check["status"], "not_linked")
        refused = self.sender.post(f"{self.url}/send-upi-link/", {"phone": "9876543210"}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertFalse(PaymentLink.objects.exists())

        sent = self.sender.post(f"{self.url}/send-upi-link/", {"phone": "9123456789"}, format="json")
        self.assertEqual(sent.status_code, 201, sent.content)
        link = PaymentLink.objects.get()
        self.assertEqual((link.phone, link.upi_check, link.amount, link.sent_by), ("9123456789", "verified", 1000, self.sender_user))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.LINK_SENT)
        msg = Message.objects.get(party=self.party)
        self.assertEqual(msg.channel, Message.SMS)
        self.assertIn("Naina Joshi", msg.body)
        self.assertEqual(sent.json()["payment_links"][0]["sent_by_name"], "Naina Joshi")

    def test_invalid_number(self):
        response = self.sender.post(f"{self.url}/upi-check/", {"phone": "12345"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_new_link_cancels_the_previous_one(self):
        self.sender.post(f"{self.url}/send-upi-link/", {}, format="json")
        self.sender.post(f"{self.url}/send-upi-link/", {"phone": "9123456789"}, format="json")
        self.assertEqual(sorted(PaymentLink.objects.values_list("status", flat=True)), ["cancelled", "sent"])

    @mock.patch.dict(os.environ, {"UPI_LOOKUP_PROVIDER": "none"})
    def test_unchecked_number_needs_staff_confirmation(self):
        self.assertEqual(self.sender.post(f"{self.url}/upi-check/", {}, format="json").json()["status"], "unknown")
        self.assertEqual(self.sender.post(f"{self.url}/send-upi-link/", {}, format="json").status_code, 400)
        ok = self.sender.post(f"{self.url}/send-upi-link/", {"staff_confirmed_upi": True}, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(PaymentLink.objects.get().upi_check, PaymentLink.UPI_STAFF_CONFIRMED)

    def test_paid_invoice_cannot_get_a_link(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.PAID)
        self.assertEqual(self.sender.post(f"{self.url}/send-upi-link/", {}, format="json").status_code, 400)

    def test_repair_staff_and_people_without_permission_cannot_send(self):
        repair = make_user("repair-tech", ["invoices.view", "payments.send_link"])
        repair.role.slug = "repair_staff"
        repair.role.save()
        self.assertEqual(client_for(repair).post(f"{self.url}/send-upi-link/", {}, format="json").status_code, 403)
        viewer = client_for(make_user("viewer-only", ["invoices.view"]))
        self.assertEqual(viewer.post(f"{self.url}/send-upi-link/", {}, format="json").status_code, 403)
        self.assertFalse(PaymentLink.objects.exists())

    def test_sandbox_payment_settles_invoice_with_upi_reference(self):
        self.sender.post(f"{self.url}/send-upi-link/", {}, format="json")
        response = self.sender.post(f"{self.url}/simulate-payment/")
        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.status, self.invoice.pay_method), (Invoice.PAID, "UPI"))
        self.assertIn("UPI RRN", self.invoice.payment_reference)
        self.assertIsNone(self.invoice.settled_by)
        self.assertEqual(PaymentLink.objects.get().status, PaymentLink.PAID)

    def test_razorpay_link_request_is_upi_only_and_texts_the_number(self):
        with mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "razorpay"}), \
                mock.patch("sales.payments._razorpay_request", return_value={"id": "plink_123", "short_url": "https://rzp.io/i/abc"}) as rp:
            response = self.sender.post(f"{self.url}/send-upi-link/", {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        method, path, payload = rp.call_args.args
        self.assertEqual((method, path), ("POST", "/payment_links"))
        self.assertTrue(payload["upi_link"])
        self.assertEqual((payload["amount"], payload["customer"]["contact"], payload["notify"]["sms"]), (100000, "+919876543211", True))
        self.assertEqual(payload["notes"]["sent_by"], "Naina Joshi")
        link = PaymentLink.objects.get()
        self.assertEqual((link.provider, link.provider_link_id, link.url), ("razorpay", "plink_123", "https://rzp.io/i/abc"))

    def test_razorpay_webhook_requires_valid_signature_and_settles(self):
        link = PaymentLink.objects.create(
            invoice=self.invoice, phone="9876543211", upi_check="verified", amount=1000,
            provider="razorpay", provider_link_id="plink_xyz", sent_by=self.sender_user,
        )
        body = json.dumps({
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": "plink_xyz"}},
                "payment": {"entity": {"id": "pay_ABC", "acquirer_data": {"rrn": "412312341234"}}},
            },
        }).encode()
        url = "/api/payments/razorpay-webhook/"
        with mock.patch.dict(os.environ, {"RAZORPAY_WEBHOOK_SECRET": "whsec"}):
            bad = APIClient().post(url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="nope")
            self.assertEqual(bad.status_code, 400)
            sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
            ok = APIClient().post(url, body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sig)
        self.assertEqual(ok.status_code, 200)
        link.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual((link.status, link.provider_payment_id), ("paid", "pay_ABC"))
        self.assertEqual(self.invoice.payment_reference, "UPI RRN 412312341234 / pay_ABC")
        self.assertEqual(self.invoice.status, Invoice.PAID)
