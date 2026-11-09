"""Paying an invoice in instalments, and the customer statement built from it."""
from datetime import date

from accounting.models import BankEntry, CashEntry
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from catalog.models import StockPoint
from sales.models import Invoice, InvoiceItem, InvoicePayment
from django.test import TestCase


class Base(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(name="Shop A", slug="Shop A".lower().replace(" ", "-"), kind="shop")
        self.user = make_user("cashier", ("invoices.view", "invoices.settle", "invoices.create", "parties.view"),
                              stock_point=self.shop)
        self.client_ = client_for(self.user)
        self.party = Party.objects.create(name="Asha Traders", type=Party.DEALER, phone="9876500000", joined=date.today())

    def invoice(self, code, total=10000, qty=2, status=Invoice.LINK_SENT, when=None, **extra):
        inv = Invoice.objects.create(code=code, party=self.party, stock_point=self.shop, date=when or date.today(),
                                     status=status, **extra)
        InvoiceItem.objects.create(invoice=inv, description="Laptop", qty=qty, price=total // qty)
        return inv

    def pay(self, inv, amount=None, method="Cash", reference=""):
        body = {"pay_method": method, "payment_reference": reference}
        if amount is not None:
            body["amount"] = amount
        return self.client_.post(f"/api/invoices/{inv.pk}/settle/", body, format="json")


class PartPaymentTests(Base):
    def test_part_payment_leaves_the_rest_owed(self):
        inv = self.invoice("INV-1")
        response = self.pay(inv, 4000)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["amount_paid"], response.json()["balance_due"]), (4000, 6000))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.LINK_SENT)
        self.assertEqual(CashEntry.objects.get().amount, 4000)

    def test_last_instalment_settles_and_books_only_that(self):
        inv = self.invoice("INV-1")
        self.pay(inv, 4000)
        self.assertEqual(self.pay(inv, 6000, method="UPI", reference="UTR1").status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.PAID)
        self.assertEqual(CashEntry.objects.get().amount, 4000)
        self.assertEqual(BankEntry.objects.get().amount, 6000)

    def test_mark_paid_after_a_part_collects_the_balance(self):
        inv = self.invoice("INV-1")
        self.pay(inv, 3000)
        self.assertEqual(self.pay(inv).status_code, 200)
        self.assertEqual(sorted(InvoicePayment.objects.values_list("amount", flat=True)), [3000, 7000])
        self.assertEqual(sum(CashEntry.objects.values_list("amount", flat=True)), 10000)

    def test_full_payment_without_parts_is_unchanged(self):
        inv = self.invoice("INV-1")
        self.pay(inv)
        self.assertFalse(InvoicePayment.objects.exists())
        self.assertEqual(CashEntry.objects.get().amount, 10000)

    def test_too_much_or_nothing_is_refused(self):
        inv = self.invoice("INV-1")
        for amount in (0, -5, 10001, "abc"):
            self.assertEqual(self.pay(inv, amount).status_code, 400, amount)

    def test_part_paid_invoice_cannot_be_cancelled(self):
        inv = self.invoice("INV-1")
        self.pay(inv, 1000)
        self.assertEqual(self.client_.post(f"/api/invoices/{inv.pk}/cancel/", {"reason": "x"}, format="json").status_code, 400)


class StatementTests(Base):
    def statement(self, client=None):
        response = (client or self.client_).get(f"/api/parties/{self.party.pk}/statement/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_rows_quantity_credit_and_running_balance(self):
        a = self.invoice("INV-1", total=10000, qty=2, when=date(2026, 1, 1))
        self.invoice("INV-2", total=5000, qty=1, when=date(2026, 2, 1))
        self.invoice("INV-3", total=3000, qty=3, when=date(2026, 3, 1), status=Invoice.PAID)
        self.invoice("INV-X", total=999, qty=1, when=date(2026, 3, 2), status=Invoice.CANCELLED)
        self.pay(a, 4000)
        data = self.statement()
        self.assertEqual(data["party"]["name"], "Asha Traders")
        rows = [(r["code"], r["qty"], r["amount"], r["paid"], r["credit"], r["balance"]) for r in data["rows"]]
        self.assertEqual(rows, [
            ("INV-1", 2, 10000, 4000, 6000, 6000),
            ("INV-2", 1, 5000, 0, 5000, 11000),
            ("INV-3", 3, 3000, 3000, 0, 11000),
        ])
        self.assertEqual(data["totals"], {"qty": 6, "amount": 18000, "paid": 7000, "credit": 11000, "balance": 11000})
        self.assertEqual(data["rows"][0]["payments"][0]["amount"], 4000)

    def test_items_are_named(self):
        self.invoice("INV-1", total=10000, qty=2)
        self.assertEqual(self.statement()["rows"][0]["items"], [{"name": "Laptop", "qty": 2}])

    def test_due_only_and_date_filters(self):
        self.invoice("INV-1", total=10000, when=date(2026, 1, 1))
        self.invoice("INV-2", total=5000, when=date(2026, 2, 1))
        self.invoice("INV-3", total=3000, when=date(2026, 3, 1), status=Invoice.PAID)
        due = self.client_.get(f"/api/parties/{self.party.pk}/statement/?due=1").json()
        self.assertEqual([r["code"] for r in due["rows"]], ["INV-1", "INV-2"])
        feb = self.client_.get(f"/api/parties/{self.party.pk}/statement/?from=2026-02-01&to=2026-03-31").json()
        self.assertEqual([r["code"] for r in feb["rows"]], ["INV-2", "INV-3"])
        self.assertEqual((feb["opening"], feb["rows"][0]["balance"], feb["totals"]["balance"]), (10000, 15000, 15000))

    def test_bad_dates_are_refused(self):
        for query in ("from=abc", "from=2026-03-01&to=2026-01-01"):
            self.assertEqual(self.client_.get(f"/api/parties/{self.party.pk}/statement/?{query}").status_code, 400)

    def test_pdf_download(self):
        self.invoice("INV-1")
        response = self.client_.get(f"/api/parties/{self.party.pk}/statement/pdf/?due=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("Statement-Asha-Traders", response["Content-Disposition"])

    def test_pdf_needs_invoice_permission(self):
        viewer = client_for(make_user("viewer2", ("parties.view",), stock_point=self.shop))
        self.assertEqual(viewer.get(f"/api/parties/{self.party.pk}/statement/pdf/").status_code, 403)

    def test_advance_is_labelled(self):
        self.invoice("ADV-1", status=Invoice.PAID, is_advance=True)
        self.assertEqual(self.statement()["rows"][0]["kind"], "Advance")

    def test_needs_invoice_permission(self):
        viewer = client_for(make_user("viewer", ("parties.view",), stock_point=self.shop))
        self.assertEqual(viewer.get(f"/api/parties/{self.party.pk}/statement/").status_code, 403)

    def test_other_stores_invoices_are_left_out(self):
        other = StockPoint.objects.create(name="Shop B", slug="Shop B".lower().replace(" ", "-"), kind="shop")
        Invoice.objects.create(code="INV-B", party=self.party, stock_point=other, date=date.today())
        self.assertEqual(self.statement()["rows"], [])


class ListFilterTests(Base):
    def setUp(self):
        super().setUp()
        self.other = Party.objects.create(name="Paid Up Ltd", type=Party.RETAIL, phone="9876511111", joined=date.today())

    def names(self, query=""):
        response = self.client_.get(f"/api/parties/?{query}")
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        return {row["name"]: row for row in rows}

    def test_due_only_lists_customers_who_owe(self):
        self.invoice("INV-1", total=10000)
        Invoice.objects.create(code="INV-P", party=self.other, stock_point=self.shop, date=date.today(), status=Invoice.PAID)
        rows = self.names("due=1")
        self.assertEqual(set(rows), {"Asha Traders"})
        self.assertEqual(rows["Asha Traders"]["amount_due"], 10000)

    def test_date_range(self):
        self.invoice("INV-1", when=date(2026, 1, 5))
        Invoice.objects.create(code="INV-P", party=self.other, stock_point=self.shop, date=date(2026, 3, 5))
        self.assertEqual(set(self.names("from=2026-03-01&to=2026-03-31")), {"Paid Up Ltd"})

    def test_no_filter_lists_everyone(self):
        self.assertEqual(set(self.names()), {"Asha Traders", "Paid Up Ltd"})

    def test_bad_date_is_refused(self):
        self.assertEqual(self.client_.get("/api/parties/?from=nope").status_code, 400)
