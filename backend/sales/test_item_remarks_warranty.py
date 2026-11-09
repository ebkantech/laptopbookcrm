"""Remarks and the guarantee written on each sale line, and finding a unit by serial number."""
import os
from unittest import mock

from django.test import TestCase, override_settings

from catalog.models import StockSerial
from crmbook_backend.testing import client_for, make_user
from rentals.models import add_months
from sales.documents import invoice_document, warranty_text
from sales.models import Invoice
from sales.test_stock_deduction import StockFixture
from warranty.models import Warranty


@mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"})
@override_settings(WARRANTY_SALES_DAYS=0)
class ItemRemarksWarrantyTests(StockFixture, TestCase):
    def setUp(self):
        self.make_fixture()

    def pay(self, invoice_id):
        response = self.staff.post(f"/api/invoices/{invoice_id}/settle/", {"pay_method": "Cash"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_remarks_and_warranty_are_saved_and_printed(self):
        response = self.sell([
            {"variant": self.laptop.id, "qty": 1, "price": 40000, "remarks": "  Charger   and bag included ", "warranty_months": 12},
            {"variant": self.charger.id, "qty": 1, "price": 1500},
        ])
        self.assertEqual(response.status_code, 201, response.content)
        laptop, charger = response.json()["items"]
        self.assertEqual((laptop["remarks"], laptop["warranty_months"]), ("Charger and bag included", 12))
        self.assertEqual((charger["remarks"], charger["warranty_months"]), ("", None))
        doc = invoice_document(Invoice.objects.get(pk=response.json()["id"]))
        self.assertEqual(doc["items"][0]["warranty"], "Warranty: 1 year from the date of purchase")
        self.assertEqual(doc["items"][1]["warranty"], "")  # nothing promised -> nothing printed

    def test_discount_is_not_counted_and_remarks_go_under_the_table(self):
        response = self.staff.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.kb.id, "date": "2026-11-08",
            "items": [{"variant": self.laptop.id, "qty": 1, "price": 40000, "remarks": "No warranty on this unit"}],
            "discount_percent": 10, "discount_reason": "Regular customer",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        doc = invoice_document(Invoice.objects.get(pk=response.json()["id"]))
        laptop, discount = doc["items"]
        self.assertEqual((laptop["n"], laptop["qty"]), (1, 1))
        self.assertEqual((discount["n"], discount["qty"], discount["adjustment"]), ("", None, True))
        self.assertEqual(doc["total_qty"], 1)
        self.assertEqual(doc["remarks"], [{"n": 1, "item": laptop["description"], "text": "No warranty on this unit"}])
        from sales.documents import render_invoice_pdf
        pdf = render_invoice_pdf(Invoice.objects.get(pk=response.json()["id"]))
        open(os.environ.get("PDF_OUT", os.devnull), "wb").write(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_paid_invoice_makes_a_warranty_only_for_items_that_promised_one(self):
        response = self.sell([
            {"variant": self.laptop.id, "qty": 1, "price": 40000, "warranty_months": 6},
            {"variant": self.charger.id, "qty": 1, "price": 1500},
        ])
        invoice = Invoice.objects.get(pk=response.json()["id"])
        self.pay(invoice.id)
        warranty = Warranty.objects.get(invoice=invoice)  # one only: the charger had none
        invoice.refresh_from_db()
        self.assertIn("Latitude", warranty.item_label)
        self.assertEqual(warranty.end_date, add_months(warranty.start_date, 6))

    def test_no_warranty_promised_means_no_warranty(self):
        response = self.sell([{"variant": self.laptop.id, "qty": 1, "price": 40000}])
        self.pay(response.json()["id"])
        self.assertFalse(Warranty.objects.exists())

    def test_warranty_months_must_be_sensible(self):
        response = self.sell([{"variant": self.laptop.id, "qty": 1, "price": 40000, "warranty_months": 0}])
        self.assertEqual(response.status_code, 400)

    def test_warranty_wording(self):
        self.assertEqual(warranty_text(3), "Warranty: 3 months from the date of purchase")
        self.assertEqual(warranty_text(24), "Warranty: 2 years from the date of purchase")
        self.assertEqual(warranty_text(None), "")


class FindBySerialTests(StockFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        user = make_user("finder", ["invoices.create"], stock_point=self.kb)
        self.client_ = client_for(user)
        StockSerial.objects.create(variant=self.laptop, stock_point=self.kb, serial_number="5CG1234XYZ", received_by=user)
        StockSerial.objects.create(variant=self.laptop, stock_point=self.np, serial_number="5CG1234OTHER", received_by=user)

    def test_finds_units_on_this_shops_shelf(self):
        rows = self.client_.get(f"/api/stock-serials/find/?q=1234x&stock_point={self.kb.id}").json()
        self.assertEqual([(r["serial_number"], r["variant"]) for r in rows], [("5CG1234XYZ", self.laptop.id)])

    def test_short_query_finds_nothing(self):
        self.assertEqual(self.client_.get(f"/api/stock-serials/find/?q=5C&stock_point={self.kb.id}").json(), [])

    def test_another_shops_shelf_is_refused(self):
        self.assertEqual(self.client_.get(f"/api/stock-serials/find/?q=5CG&stock_point={self.np.id}").status_code, 403)
