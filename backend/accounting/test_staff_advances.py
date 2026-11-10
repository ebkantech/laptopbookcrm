"""Accounting -> Staff advances: give, recover by cash or salary, books and access."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounting.models import BankAccount, BankEntry, CashEntry, Expense, ExpenseCategory, StaffAdvanceEntry
from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user


class StaffAdvanceTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="adv-shop", name="Karol Bagh", kind=StockPoint.SHOP)
        self.other = StockPoint.objects.create(slug="adv-other", name="Saket", kind=StockPoint.SHOP)
        self.owner = make_user("adv-owner", superuser=True)
        self.tech = make_user("adv-tech", perms=["repairs.view"], stock_point=self.shop)
        self.tech.first_name, self.tech.last_name = "Rohit", "Kumar"
        self.tech.save()
        self.far = make_user("adv-far", perms=["repairs.view"], stock_point=self.other)
        ExpenseCategory.objects.get_or_create(slug="salary", defaults={"label": "Salary"})
        BankAccount.objects.get_or_create(name="Main", defaults={"is_default": True}) if hasattr(BankAccount, "is_default") else None
        self.c = client_for(self.owner)
        self.today = timezone.localdate()

    def post(self, user, **body):
        body.setdefault("date", self.today.isoformat())
        return self.c.post(f"/api/staff-advances/{user.id}/", body, format="json")

    def row(self, user):
        return next(r for r in self.c.get("/api/staff-advances/").json()["staff"] if r["id"] == user.id)

    def test_give_then_recover_by_cash_and_salary(self):
        r = self.post(self.tech, kind="given", amount=5000, method="Cash", note="Festival")
        self.assertEqual(r.status_code, 200, r.content)
        cash = CashEntry.objects.get(staff_advance__staff=self.tech)
        self.assertEqual((cash.type, cash.amount), (CashEntry.OUT, 5000))
        self.assertIn("Advance to Rohit Kumar", cash.particulars)
        self.assertFalse(Expense.objects.exists())  # an advance isn't an expense
        self.assertEqual(self.row(self.tech)["outstanding"], 5000)

        self.assertEqual(self.post(self.tech, kind="returned", amount=1000, method="UPI").status_code, 200)
        self.assertEqual(BankEntry.objects.get(staff_advance__staff=self.tech).type, BankEntry.IN)

        r = self.post(self.tech, kind="salary", amount=3000)
        self.assertEqual(r.status_code, 200, r.content)
        expense = Expense.objects.get()
        self.assertEqual((expense.amount, expense.category.slug, expense.payment_status), (3000, "salary", Expense.PAID))
        self.assertEqual(expense.stock_point, self.shop)
        self.assertEqual(CashEntry.objects.count() + BankEntry.objects.count(), 2)  # salary adjustment posts nothing

        row = self.row(self.tech)
        self.assertEqual((row["given"], row["recovered"], row["outstanding"]), (5000, 4000, 1000))
        detail = self.c.get(f"/api/staff-advances/{self.tech.id}/").json()
        self.assertEqual([e["kind"] for e in detail["entries"]][-1], "given")

    def test_cannot_recover_more_than_owed(self):
        self.assertEqual(self.post(self.tech, kind="returned", amount=10, method="Cash").status_code, 400)
        self.post(self.tech, kind="given", amount=2000, method="Cash")
        r = self.post(self.tech, kind="salary", amount=2500)
        self.assertEqual(r.status_code, 400)
        self.assertIn("owes only", str(r.json()))

    def test_validation(self):
        self.assertEqual(self.post(self.tech, kind="given", amount=100).status_code, 400)  # no method
        future = (self.today + timedelta(days=2)).isoformat()
        self.assertEqual(self.post(self.tech, kind="given", amount=100, method="Cash", date=future).status_code, 400)

    def test_posted_entry_is_locked_in_the_cash_book(self):
        self.post(self.tech, kind="given", amount=500, method="Cash")
        entry = CashEntry.objects.get()
        r = self.c.delete(f"/api/cash-entries/{entry.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("staff advance", str(r.json()).lower())

    def test_staff_list_includes_everyone_and_only_managers_see_it(self):
        names = {r["username"] for r in self.c.get("/api/staff-advances/").json()["staff"]}
        self.assertTrue({"adv-tech", "adv-far"} <= names)
        self.assertEqual(client_for(self.tech).get("/api/staff-advances/").status_code, 403)
