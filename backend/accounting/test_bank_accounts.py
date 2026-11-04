"""Several bank accounts side by side, and who may open one: POST
/api/bank-accounts/ always creates a new account; only the Owner / Super
Admin (Owner role) or a superuser may call it."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounting.models import BankAccount, BankEntry, CashEntry
from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user, results

BANK_PERMS = ["bankbook.view", "bankbook.edit", "bankbook.reconcile"]


class MultipleBankAccountTests(TestCase):
    def setUp(self):
        self.owner_user = make_user("acct-owner", BANK_PERMS, owner=True)
        self.owner = client_for(self.owner_user)
        self.legacy = CashEntry.objects.create(date=date(2026, 9, 1), particulars="Shop float", type="in", amount=4200, by=self.owner_user)

    def open(self, name, opening, **extra):
        response = self.owner.post("/api/bank-accounts/", {"name": name, "opening": opening, **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def accounts(self):
        return {a["name"]: a for a in results(self.owner.get("/api/bank-accounts/"))}

    def test_each_new_account_is_its_own_record_and_leaves_the_others_alone(self):
        hdfc = self.open("HDFC Bank", 50000)
        sbi = self.open("SBI Bank", 100000)
        self.assertNotEqual(hdfc["id"], sbi["id"])
        listed = self.accounts()
        self.assertEqual((listed["HDFC Bank"]["opening"], listed["HDFC Bank"]["balance"]), (50000, 50000))
        self.assertEqual((listed["SBI Bank"]["opening"], listed["SBI Bank"]["balance"]), (100000, 100000))

        self.open("Cash Account", 25000)
        listed = self.accounts()
        self.assertEqual(len(listed), 3)
        self.assertEqual((listed["HDFC Bank"]["id"], listed["HDFC Bank"]["opening"]), (hdfc["id"], 50000))
        self.assertEqual((listed["SBI Bank"]["id"], listed["SBI Bank"]["opening"]), (sbi["id"], 100000))
        self.assertEqual(listed["Cash Account"]["opening"], 25000)

    def test_editing_one_account_changes_only_that_account(self):
        hdfc = self.open("HDFC Bank", 50000)
        sbi = self.open("SBI Bank", 100000)
        response = self.owner.patch(f"/api/bank-accounts/{sbi['id']}/", {"name": "SBI Bank — Current", "opening": 120000}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(BankAccount.objects.get(pk=hdfc["id"]).name, "HDFC Bank")
        self.assertEqual(BankAccount.objects.get(pk=hdfc["id"]).opening, 50000)
        self.assertEqual(BankAccount.objects.get(pk=sbi["id"]).opening, 120000)

    def test_entries_and_balances_never_mix_between_accounts(self):
        hdfc = self.open("HDFC Bank", 50000)
        sbi = self.open("SBI Bank", 100000)
        for account, kind, amount in ((hdfc, "in", 7000), (sbi, "out", 3000), (hdfc, "out", 2000)):
            response = self.owner.post("/api/bank-entries/", {
                "account": account["id"], "date": date.today().isoformat(), "particulars": "Manual", "type": kind, "amount": amount,
            }, format="json")
            self.assertEqual(response.status_code, 201, response.content)
        listed = self.accounts()
        self.assertEqual(listed["HDFC Bank"]["balance"], 50000 + 7000 - 2000)
        self.assertEqual(listed["SBI Bank"]["balance"], 100000 - 3000)
        self.assertEqual(sorted(e["amount"] for e in listed["HDFC Bank"]["entries"]), [2000, 7000])
        self.assertEqual([e["amount"] for e in results(self.owner.get(f"/api/bank-entries/?account={sbi['id']}"))], [3000])

    def test_opening_balance_is_stored_once_with_no_ledger_entry(self):
        self.open("HDFC Bank", 50000)
        self.open("SBI Bank", 100000)
        self.assertFalse(BankEntry.objects.exists())  # the opening lives on the account, not as a posting
        self.assertEqual(CashEntry.objects.get(), self.legacy)  # existing books untouched

    def test_a_new_account_only_takes_over_invoice_payments_when_asked(self):
        hdfc = self.open("HDFC Bank", 50000)
        self.assertTrue(hdfc["is_default"])  # the first account receives invoice payments
        self.open("SBI Bank", 100000, is_default=False)
        self.assertEqual(BankAccount.objects.get(is_default=True).id, hdfc["id"])

    def test_same_name_twice_is_two_accounts_told_apart_by_id(self):
        a = self.open("HDFC Bank", 1000)
        b = self.open("HDFC Bank", 2000)
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(sorted(BankAccount.objects.values_list("opening", flat=True)), [1000, 2000])

    def test_owner_still_manages_accounts_while_one_store_is_in_view(self):
        shop = StockPoint.objects.create(slug="acct-shop", name="Lajpat Nagar", kind=StockPoint.SHOP)
        self.open("HDFC Bank", 50000)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.owner_user).access_token}",
                           HTTP_X_ACTIVE_STORE=str(shop.id))
        self.assertEqual([a["name"] for a in results(client.get("/api/bank-accounts/"))], ["HDFC Bank"])
        self.assertEqual(client.post("/api/bank-accounts/", {"name": "SBI Bank", "opening": 1}, format="json").status_code, 201)


class OpenAccountPermissionTests(TestCase):
    """Only the Owner / Super Admin or a superuser opens accounts -- holding
    bankbook.edit isn't enough."""

    def setUp(self):
        self.shop = StockPoint.objects.create(slug="perm-shop", name="Karol Bagh", kind=StockPoint.SHOP)
        self.existing = BankAccount.objects.create(name="HDFC Bank", opening=50000, is_default=True)

    def attempt(self, user):
        return client_for(user).post("/api/bank-accounts/", {"name": "SBI Bank", "opening": 100000}, format="json")

    def test_owner_and_superuser_can_open_accounts(self):
        for user in (make_user("perm-owner", BANK_PERMS, owner=True), make_user("perm-super", superuser=True)):
            self.assertEqual(self.attempt(user).status_code, 201)
        self.assertEqual(BankAccount.objects.count(), 3)

    def test_admin_staff_and_rental_staff_get_403_and_nothing_changes(self):
        admin = make_user("perm-admin", ["roles.manage", *BANK_PERMS], stock_point=self.shop)
        staff = make_user("perm-staff", ["invoices.view", *BANK_PERMS], stock_point=self.shop)
        rental = make_user("perm-rental", ["rentals.view", "rentals.manage"], stock_point=self.shop)
        for user in (admin, staff, rental):
            self.assertEqual(self.attempt(user).status_code, 403, user.username)
        self.assertEqual(list(BankAccount.objects.values_list("name", "opening")), [("HDFC Bank", 50000)])

    def test_a_forged_role_can_not_open_an_account(self):
        # an Admin claiming the Owner role in the request is refused before anything is created
        admin = make_user("perm-forger", ["roles.manage", *BANK_PERMS], stock_point=self.shop)
        from accounts.models import Role

        Role.objects.get_or_create(slug="owner", defaults={"label": "Owner"})
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin).access_token}",
                           HTTP_X_ACTIVE_ROLE=str(Role.objects.get(slug="owner").id))
        self.assertEqual(client.post("/api/bank-accounts/", {"name": "SBI Bank", "opening": 1}, format="json").status_code, 403)
        self.assertEqual(BankAccount.objects.count(), 1)

    def test_non_owners_cannot_edit_an_existing_account_either(self):
        admin = make_user("perm-admin-edit", ["roles.manage", *BANK_PERMS], stock_point=self.shop)
        response = client_for(admin).patch(f"/api/bank-accounts/{self.existing.id}/", {"opening": 1}, format="json")
        self.assertIn(response.status_code, (403, 404))
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.opening, 50000)
