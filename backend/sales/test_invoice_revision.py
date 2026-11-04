"""Revising an unpaid sale invoice (Sales & Invoices -> Revise): PATCH
/api/invoices/<id>/ with the full new set of lines. Same invoice, same
number; stock moves only by the difference; all-or-nothing."""
import os
from datetime import date
from unittest import mock

from django.test import TestCase

from accounts.models import ActivityLog
from catalog.models import Product, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from sales.models import Invoice, InvoiceItem, PaymentLink


@mock.patch.dict(os.environ, {"PAYMENT_PROVIDER": "sandbox", "UPI_LOOKUP_PROVIDER": "sandbox", "WHATSAPP_PROVIDER": "console"})
class InvoiceRevisionTests(TestCase):
    def setUp(self):
        self.user = make_user("reviser", ["invoices.view", "invoices.create", "invoices.settle", "payments.send_link"], owner=True)
        self.staff = client_for(self.user)
        self.kb = StockPoint.objects.create(slug="rev-kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Revise Buyer", type=Party.RETAIL, phone="9876543288", joined=date.today())
        self.other_party = Party.objects.create(name="Right Buyer", type=Party.RETAIL, phone="9876543277", joined=date.today())
        dell = Product.objects.create(brand="Dell", model_name="Latitude", product_code="P-REV-D", serial_tracking=True)
        hp = Product.objects.create(brand="HP", model_name="ProBook", product_code="P-REV-H")
        self.dell = Variant.objects.create(product=dell, code="V-REV-D", spec="16GB", mrp=1, sell_price=40000, cost=1)
        self.hp = Variant.objects.create(product=hp, code="V-REV-H", spec="8GB", mrp=1, sell_price=30000, cost=1)
        Stock.objects.create(variant=self.dell, stock_point=self.kb, quantity=10)
        Stock.objects.create(variant=self.hp, stock_point=self.kb, quantity=1)
        self.invoice = self.sell([self.line(self.dell, 3)])

    def line(self, variant, qty, price=None):
        return {"variant": variant.id, "qty": qty, "price": variant.sell_price if price is None else price}

    def sell(self, items):
        response = self.staff.post("/api/invoices/", {
            "party": self.party.id, "stock_point": self.kb.id, "date": date.today().isoformat(), "items": items,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def revise(self, items, client=None, invoice=None, **fields):
        return (client or self.staff).patch(f"/api/invoices/{(invoice or self.invoice)['id']}/", {"items": items, **fields}, format="json")

    def shelf(self, variant):
        return Stock.objects.get(variant=variant, stock_point=self.kb).quantity

    def lines(self):
        return sorted((i.variant_id, i.qty, i.price) for i in InvoiceItem.objects.filter(invoice_id=self.invoice["id"]))

    # -- 3, 4, 5, 7, 8, 9: the brief's own example ---------------------
    def test_dell_3_to_2_plus_one_hp_restores_one_dell_and_takes_one_hp(self):
        self.assertEqual(self.shelf(self.dell), 7)
        response = self.revise([self.line(self.dell, 2), self.line(self.hp, 1)])
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["id"], data["code"]), (self.invoice["id"], self.invoice["code"]))
        self.assertEqual(data["status"], Invoice.LINK_SENT)
        self.assertEqual(data["total"], 2 * 40000 + 30000)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual((self.shelf(self.dell), self.shelf(self.hp)), (8, 0))

    def test_dell_2_to_4_takes_only_2_more(self):
        self.revise([self.line(self.dell, 2)])
        self.assertEqual(self.shelf(self.dell), 8)
        self.assertEqual(self.revise([self.line(self.dell, 4)]).status_code, 200)
        self.assertEqual(self.shelf(self.dell), 6)

    def test_removing_a_product_puts_all_of_it_back(self):
        self.revise([self.line(self.dell, 3), self.line(self.hp, 1)])
        self.assertEqual(self.revise([self.line(self.hp, 1)]).status_code, 200)
        self.assertEqual((self.shelf(self.dell), self.shelf(self.hp)), (10, 0))
        self.assertEqual(self.lines(), [(self.hp.id, 1, 30000)])

    # -- 6: price / discount -------------------------------------------
    def test_a_discounted_price_recalculates_the_total_and_moves_no_stock(self):
        response = self.revise([self.line(self.dell, 3, price=37500)])
        self.assertEqual(response.json()["total"], 3 * 37500)
        self.assertEqual(self.shelf(self.dell), 7)
        print_data = self.staff.get(f"/api/invoices/{self.invoice['id']}/print-data/")
        self.assertEqual(print_data.status_code, 200)
        self.assertIn("37500", str(print_data.json()))

    def test_customer_can_be_corrected_with_the_lines(self):
        response = self.revise([self.line(self.dell, 3)], party=self.other_party.id)
        self.assertEqual(response.json()["party"], self.other_party.id)
        self.assertEqual(response.json()["date"], self.invoice["date"])

    # -- 10, 11: refusal and rollback ----------------------------------
    def test_more_than_the_shelf_refuses_and_changes_nothing(self):
        response = self.revise([self.line(self.dell, 2), self.line(self.hp, 2)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("only 1 in stock at Karol Bagh", response.json()["items"][0])
        self.assertEqual((self.shelf(self.dell), self.shelf(self.hp)), (7, 1))
        self.assertEqual(self.lines(), [(self.dell.id, 3, 40000)])

    def test_a_failure_while_saving_rolls_back_stock_and_lines(self):
        real_create = InvoiceItem.objects.create
        calls = []

        def fail_on_second_line(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("database went away")
            return real_create(**kwargs)

        with mock.patch.object(InvoiceItem.objects, "create", side_effect=fail_on_second_line):
            with self.assertRaises(RuntimeError):
                self.revise([self.line(self.dell, 1), self.line(self.hp, 1)])
        self.assertEqual((self.shelf(self.dell), self.shelf(self.hp)), (7, 1))
        self.assertEqual(self.lines(), [(self.dell.id, 3, 40000)])

    # -- 12: paid / cancelled ------------------------------------------
    def test_paid_and_cancelled_invoices_cannot_be_revised(self):
        self.staff.post(f"/api/invoices/{self.invoice['id']}/settle/", {"pay_method": "Cash"}, format="json")
        response = self.revise([self.line(self.dell, 1)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Refund", str(response.json()))

        cancelled = self.sell([self.line(self.dell, 1)])
        self.staff.post(f"/api/invoices/{cancelled['id']}/cancel/", {"reason": "typo"}, format="json")
        self.assertEqual(self.revise([self.line(self.dell, 2)], invoice=cancelled).status_code, 400)
        self.assertEqual(self.shelf(self.dell), 7)
        self.assertEqual(Invoice.objects.get(pk=self.invoice["id"]).status, Invoice.PAID)

    def test_overdue_invoice_is_still_unpaid_and_can_be_revised(self):
        Invoice.objects.filter(pk=self.invoice["id"]).update(status=Invoice.OVERDUE)
        self.assertEqual(self.revise([self.line(self.dell, 1)]).status_code, 200)
        self.assertEqual(self.shelf(self.dell), 9)

    def test_needs_invoices_create_on_the_server_not_just_a_hidden_button(self):
        viewer = client_for(make_user("rev-viewer", ["invoices.view"], stock_point=self.kb))
        self.assertEqual(self.revise([self.line(self.dell, 1)], client=viewer).status_code, 403)
        self.assertEqual(self.shelf(self.dell), 7)

    # -- payment links and the money side ------------------------------
    def test_a_changed_total_stops_the_old_payment_link_and_a_late_payment_on_it_does_not_settle(self):
        sent = self.staff.post(f"/api/invoices/{self.invoice['id']}/send-upi-link/", {"phone": "9123456789", "staff_confirmed_upi": True}, format="json")
        self.assertEqual(sent.status_code, 201, sent.content)
        link = PaymentLink.objects.get(invoice_id=self.invoice["id"])
        self.revise([self.line(self.dell, 2)])
        link.refresh_from_db()
        self.assertEqual(link.status, PaymentLink.CANCELLED)

        from sales import payments

        payments.mark_link_paid(link, payment_id="late_pay", rrn="1")  # the customer paid the stale link anyway
        link.refresh_from_db()
        invoice = Invoice.objects.get(pk=self.invoice["id"])
        self.assertEqual(link.status, PaymentLink.PAID)  # the money is on record...
        self.assertEqual(invoice.status, Invoice.LINK_SENT)  # ...but the revised invoice isn't settled with it

    def test_same_total_keeps_the_payment_link(self):
        self.staff.post(f"/api/invoices/{self.invoice['id']}/send-upi-link/", {"phone": "9123456789", "staff_confirmed_upi": True}, format="json")
        self.revise([self.line(self.dell, 1, price=120000)])
        self.assertEqual(PaymentLink.objects.get(invoice_id=self.invoice["id"]).status, PaymentLink.SENT)

    # -- revision history ----------------------------------------------
    def test_the_revision_is_in_the_activity_log_with_who_totals_and_lines(self):
        self.revise([self.line(self.dell, 2), self.line(self.hp, 1)])
        row = ActivityLog.objects.filter(record_type="sales.invoice", record_id=str(self.invoice["id"]), action="revised").get()
        self.assertEqual(row.actor, self.user)
        self.assertIn("₹120,000 → ₹110,000", row.description)
        self.assertIn("Dell Latitude (16GB) ×3 ₹120,000 → ×2 ₹80,000", row.description)
        self.assertIn("added HP ProBook (8GB) ×1", row.description)
        self.assertEqual(row.changes["total"], [120000, 110000])

    # -- 13: serial-tracked laptops ------------------------------------
    def test_serial_tracked_units_stay_recorded_while_the_shelf_count_moves(self):
        serials = [StockSerial.objects.create(variant=self.dell, stock_point=self.kb, serial_number=f"DL{n:05d}", received_by=self.user)
                   for n in range(3)]
        self.revise([self.line(self.dell, 1)])
        self.assertEqual(self.shelf(self.dell), 9)
        self.assertEqual(list(StockSerial.objects.filter(variant=self.dell).order_by("id")), serials)
