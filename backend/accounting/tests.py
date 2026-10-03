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
