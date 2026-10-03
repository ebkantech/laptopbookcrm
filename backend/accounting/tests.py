from datetime import date

from django.test import TestCase

from accounting.models import BankAccount, BankEntry, CashEntry
from crmbook_backend.testing import client_for, make_user, results


class CashBookTests(TestCase):
    def setUp(self):
        self.accountant_user = make_user("accountant", ["cashbook.view", "cashbook.edit"])
        self.accountant = client_for(self.accountant_user)

    def test_create_entry_records_who_made_it(self):
        response = self.accountant.post("/api/cash-entries/", {
            "date": date.today().isoformat(), "particulars": "Shop rent", "type": CashEntry.OUT, "amount": 15000,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(CashEntry.objects.get().by, self.accountant_user)

    def test_view_only_cannot_write(self):
        viewer = client_for(make_user("cash-viewer", ["cashbook.view"]))
        self.assertEqual(viewer.get("/api/cash-entries/").status_code, 200)
        response = viewer.post("/api/cash-entries/", {
            "date": date.today().isoformat(), "particulars": "x", "type": CashEntry.IN, "amount": 1,
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client_for(make_user("no-cash")).get("/api/cash-entries/").status_code, 403)


class BankBookTests(TestCase):
    def setUp(self):
        self.account = BankAccount.objects.create(name="HDFC Current", opening=100000)
        self.other = BankAccount.objects.create(name="SBI Savings", opening=0)
        BankEntry.objects.create(account=self.account, date=date.today(), particulars="Opening balance", type=BankEntry.IN, amount=100000)
        BankEntry.objects.create(account=self.account, date=date.today(), particulars="Customer payment", type=BankEntry.IN, amount=25000)
        self.debit = BankEntry.objects.create(account=self.account, date=date.today(), particulars="Supplier", type=BankEntry.OUT, amount=5000)
        BankEntry.objects.create(account=self.other, date=date.today(), particulars="Interest", type=BankEntry.IN, amount=100)
        self.banker = client_for(make_user("banker", ["bankbook.view", "bankbook.edit", "bankbook.reconcile"]))

    def test_balance_is_opening_plus_credits_minus_debits(self):
        accounts = {a["name"]: a for a in results(self.banker.get("/api/bank-accounts/"))}
        # The "Opening balance" entry isn't double-counted on top of `opening`.
        self.assertEqual(accounts["HDFC Current"]["balance"], 100000 + 25000 - 5000)
        self.assertEqual(accounts["SBI Savings"]["balance"], 100)

    def test_entries_filter_by_account(self):
        entries = results(self.banker.get("/api/bank-entries/", {"account": self.other.id}))
        self.assertEqual([e["particulars"] for e in entries], ["Interest"])

    def test_toggle_reconciled_needs_reconcile_permission(self):
        url = f"/api/bank-entries/{self.debit.id}/toggle-reconciled/"
        self.assertTrue(self.banker.post(url).json()["reconciled"])
        self.assertFalse(self.banker.post(url).json()["reconciled"])

        editor = client_for(make_user("bank-editor", ["bankbook.view", "bankbook.edit"]))
        self.assertEqual(editor.post(url).status_code, 403)


class InvoicePaymentPostingTests(TestCase):
    """Invoice payments post themselves into the cash / bank book."""

    def setUp(self):
        from catalog.models import Product, Stock, StockPoint, Variant
        from parties.models import Party
        from sales.models import Invoice, InvoiceItem

        self.Invoice = Invoice
        self.cashier_user = make_user("cashier", ["invoices.view", "invoices.settle", "cashbook.view", "cashbook.edit", "bankbook.view", "bankbook.edit"])
        self.cashier = client_for(self.cashier_user)
        shop = StockPoint.objects.create(slug="shop", name="Shop", kind=StockPoint.SHOP)
        party = Party.objects.create(name="Payer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        variant = Variant.objects.create(
            product=Product.objects.create(model_name="Laptop", product_code="P-1"), code="V-1", spec="x", mrp=1, sell_price=1, cost=1,
        )
        Stock.objects.create(variant=variant, stock_point=shop, quantity=5)

        def invoice(code, amount):
            inv = Invoice.objects.create(code=code, party=party, stock_point=shop, date=date.today())
            InvoiceItem.objects.create(invoice=inv, variant=variant, qty=1, price=amount)
            return inv
        self.make_invoice = invoice

    def settle(self, inv, **payment):
        return self.cashier.post(f"/api/invoices/{inv.id}/settle/", payment, format="json")

    def test_cash_payment_lands_in_the_cash_book(self):
        inv = self.make_invoice("INV-C1", 25000)
        self.assertEqual(self.settle(inv, pay_method="Cash").status_code, 200)
        entry = CashEntry.objects.get(invoice=inv)
        self.assertEqual((entry.type, entry.amount, entry.by), (CashEntry.IN, 25000, self.cashier_user))
        self.assertIn("INV-C1", entry.particulars)
        self.assertFalse(BankEntry.objects.exists())
        listed = results(self.cashier.get("/api/cash-entries/"))[0]
        self.assertEqual(listed["invoice_code"], "INV-C1")

    def test_upi_payment_lands_in_the_default_bank_account_with_reference(self):
        BankAccount.objects.create(name="Old account")
        main = BankAccount.objects.create(name="HDFC Current", is_default=True)
        inv = self.make_invoice("INV-U1", 40000)
        self.settle(inv, pay_method="UPI", payment_reference="UTR 4123")
        entry = BankEntry.objects.get(invoice=inv)
        self.assertEqual((entry.account, entry.amount, entry.reference, entry.reconciled), (main, 40000, "UTR 4123", False))
        self.assertFalse(CashEntry.objects.exists())

    def test_bank_account_is_created_if_none_exists(self):
        inv = self.make_invoice("INV-B1", 1000)
        self.settle(inv, pay_method="Bank transfer", payment_reference="NEFT 99")
        account = BankAccount.objects.get()
        self.assertTrue(account.is_default)
        self.assertEqual(account.entries.get().invoice, inv)

    def test_posted_entries_cannot_be_edited_or_deleted(self):
        inv = self.make_invoice("INV-L1", 500)
        self.settle(inv, pay_method="Cash")
        entry = CashEntry.objects.get(invoice=inv)
        self.assertEqual(self.cashier.patch(f"/api/cash-entries/{entry.id}/", {"amount": 1}, format="json").status_code, 400)
        self.assertEqual(self.cashier.delete(f"/api/cash-entries/{entry.id}/").status_code, 400)
        entry.refresh_from_db()
        self.assertEqual(entry.amount, 500)

    def test_backfill_command_posts_old_payments_once(self):
        from io import StringIO

        from django.core.management import call_command

        inv = self.make_invoice("INV-OLD", 700)
        self.Invoice.objects.filter(pk=inv.pk).update(status=self.Invoice.PAID, pay_method="UPI", paid_on=date.today())
        call_command("post_invoice_payments", "--dry-run", stdout=StringIO())
        self.assertFalse(BankEntry.objects.exists())
        call_command("post_invoice_payments", stdout=StringIO())
        call_command("post_invoice_payments", stdout=StringIO())
        self.assertEqual(BankEntry.objects.filter(invoice=inv).count(), 1)

    def test_only_one_default_account(self):
        a = self.cashier.post("/api/bank-accounts/", {"name": "HDFC", "opening": 100000}, format="json").json()
        self.assertTrue(a["is_default"])  # first account becomes the default
        b = self.cashier.post("/api/bank-accounts/", {"name": "ICICI", "is_default": True}, format="json").json()
        self.assertEqual(BankAccount.objects.get(is_default=True).id, b["id"])
        self.assertEqual(self.cashier.patch(f"/api/bank-accounts/{a['id']}/", {"opening": 250000}, format="json").status_code, 200)
