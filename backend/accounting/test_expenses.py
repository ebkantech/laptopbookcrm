"""Accounting -> Expenses: bulk entry, attachments, payments, books, P&L and access."""
import json
import os
import shutil
import tempfile
import uuid
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from accounting import expenses as svc
from accounting.models import BankEntry, CashEntry, Expense, ExpenseAttachment, ExpenseCategory, ExpensePayment
from accounts.models import ActivityLog, Permission, PermissionDeniedLog, Role
from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
BULK = "/api/expenses/bulk/"
EXPENSE_PERM = "expenses.manage"
TMP_MEDIA = tempfile.mkdtemp(prefix="expense-tests-")


def jpg(name="bill.jpg", data=JPEG):
    return SimpleUploadedFile(name, data, content_type="image/jpeg")


def png(name="receipt.png"):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def pdf(name="invoice.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


def accounts_user(username, stock_point, with_perm=True):
    """An Accounts user: the built-in "accountant" role."""
    role = Role.objects.get_or_create(slug="accountant", defaults={"label": "Accounts"})[0]
    perm = Permission.objects.get_or_create(codename=EXPENSE_PERM, defaults={"description": EXPENSE_PERM})[0]
    (role.permissions.add if with_perm else role.permissions.remove)(perm)
    from accounts.models import User
    return User.objects.create_user(username=username, password="safe-test-password", role=role, stock_point=stock_point)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class ExpenseTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.rent = ExpenseCategory.objects.get(slug="rent")
        self.other = ExpenseCategory.objects.get(slug="other")
        self.superuser = make_user("root", superuser=True)
        self.root = client_for(self.superuser)
        self.today = timezone.localdate()

    def entry(self, store=None, **fields):
        data = {"stock_point": (store or self.kb).id, "category": self.rent.id, "expense_date": self.today.isoformat(),
                "amount": 1000, "payment_status": "unpaid"}
        data.update(fields)
        return data

    def bulk(self, client, entries, files=None, key=None):
        body = {"entries": json.dumps(entries), "submission_key": key or uuid.uuid4().hex}
        for index, items in (files or {}).items():
            body[f"attachments_{index}"] = items
        return client.post(BULK, body, format="multipart")

    def files_on_disk(self):
        found = []
        for root, _, names in os.walk(TMP_MEDIA):
            found += [os.path.join(root, n) for n in names]
        return found


class BulkCreateTests(ExpenseTestBase):
    def test_categories_are_seeded_once(self):
        labels = list(ExpenseCategory.objects.values_list("label", flat=True))
        self.assertEqual(len(labels), len(set(labels)))
        self.assertIn("Repairs & Maintenance", labels)
        self.assertNotIn("Maintenance", labels)  # one category, not two equivalents
        self.assertEqual(self.other.classification, ExpenseCategory.OTHER)

    def test_create_one_expense(self):
        response = self.bulk(self.root, [self.entry(vendor="  Landlord ", reference="R-1")])
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data["count"], data["total"], data["duplicate"]), (1, 1000, False))
        expense = Expense.objects.get()
        self.assertEqual((expense.vendor, expense.created_by, expense.updated_by), ("Landlord", self.superuser, self.superuser))
        self.assertEqual(data["expenses"][0]["code"], expense.code)

    def test_many_entries_different_stores_one_request(self):
        entries = [self.entry(amount=500), self.entry(store=self.np, amount=700), self.entry(shared=True, stock_point=None, amount=900)]
        response = self.bulk(self.root, entries)
        self.assertEqual(response.status_code, 201, response.content)
        rows = list(Expense.objects.order_by("id").values_list("stock_point_id", "amount"))
        self.assertEqual(rows, [(self.kb.id, 500), (self.np.id, 700), (None, 900)])
        self.assertEqual(response.json()["total"], 2100)

    def test_creator_comes_from_the_login_not_the_payload(self):
        other = make_user("someone-else")
        self.bulk(self.root, [self.entry(created_by=other.id, updated_by=other.id)])
        self.assertEqual(Expense.objects.get().created_by, self.superuser)

    def test_missing_required_fields_name_the_entry(self):
        entries = [self.entry(), {"amount": "", "payment_status": "unpaid"}]
        response = self.bulk(self.root, entries)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual([e["entry"] for e in body["entries"]], [2])
        self.assertTrue({"category", "expense_date", "amount"} <= set(body["entries"][0]["errors"]))
        self.assertIn("Nothing was saved", body["detail"])
        self.assertFalse(Expense.objects.exists())

    def test_one_invalid_entry_saves_nothing(self):
        future = (self.today + timedelta(days=3)).isoformat()
        entries = [self.entry(), self.entry(expense_date=future), self.entry(amount=0)]
        response = self.bulk(self.root, entries, files={0: [jpg()]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual([e["entry"] for e in response.json()["entries"]], [2, 3])
        self.assertFalse(Expense.objects.exists())
        self.assertEqual(self.files_on_disk(), [])

    def test_failure_does_not_touch_earlier_expenses(self):
        self.bulk(self.root, [self.entry(amount=111)])
        self.bulk(self.root, [self.entry(), self.entry(amount=-5)])
        self.assertEqual(list(Expense.objects.values_list("amount", flat=True)), [111])

    def test_store_and_shared_must_be_unambiguous(self):
        response = self.bulk(self.root, [self.entry(shared=True)])
        self.assertIn("stock_point", response.json()["entries"][0]["errors"])

    def test_gst_cannot_exceed_amount(self):
        response = self.bulk(self.root, [self.entry(amount=100, gst_amount=200)])
        self.assertIn("gst_amount", response.json()["entries"][0]["errors"])

    def test_duplicate_submission_is_saved_once(self):
        key = uuid.uuid4().hex
        first = self.bulk(self.root, [self.entry(payment_status="paid", payment_method="Cash", payment_date=self.today.isoformat())], key=key)
        again = self.bulk(self.root, [self.entry(payment_status="paid", payment_method="Cash", payment_date=self.today.isoformat())], key=key)
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertTrue(again.json()["duplicate"])
        self.assertEqual(again.json()["expenses"][0]["id"], first.json()["expenses"][0]["id"])
        self.assertEqual((Expense.objects.count(), CashEntry.objects.count()), (1, 1))

    def test_submission_key_is_required(self):
        response = self.root.post(BULK, {"entries": json.dumps([self.entry()])}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("submission_key", response.json())

    def test_transaction_rolls_back_and_removes_written_files(self):
        entries = [self.entry(), self.entry(payment_status="paid", payment_method="UPI", payment_date=self.today.isoformat())]
        with mock.patch("accounting.expenses.record_payment", side_effect=RuntimeError("bank down")):
            with self.assertRaises(RuntimeError):
                self.bulk(self.root, entries, files={0: [jpg(), pdf()], 1: [png()]})
        self.assertFalse(Expense.objects.exists())
        self.assertFalse(ExpenseAttachment.objects.exists())
        self.assertFalse(BankEntry.objects.exists())
        self.assertEqual(self.files_on_disk(), [])

    def test_too_many_entries(self):
        with mock.patch.object(svc, "MAX_ENTRIES", 2):
            response = self.bulk(self.root, [self.entry()] * 3)
        self.assertEqual(response.status_code, 400)


class AttachmentTests(ExpenseTestBase):
    def test_many_files_for_one_expense_and_each_entry_keeps_its_own(self):
        response = self.bulk(self.root, [self.entry(amount=100), self.entry(amount=200), self.entry(amount=300)],
                             files={0: [jpg("a.jpg"), pdf("a.pdf")], 2: [png("c.png")]})
        self.assertEqual(response.status_code, 201, response.content)
        first, second, third = Expense.objects.order_by("id")
        self.assertEqual(sorted(first.attachments.values_list("original_name", flat=True)), ["a.jpg", "a.pdf"])
        self.assertFalse(second.attachments.exists())
        self.assertEqual(list(third.attachments.values_list("original_name", "content_type")), [("c.png", "image/png")])
        self.assertEqual([r["attachment_count"] for r in response.json()["expenses"]], [2, 0, 1])

    def test_stored_names_are_random_and_never_the_client_path(self):
        self.bulk(self.root, [self.entry()], files={0: [jpg("../../etc/evil name.jpeg")]})
        att = ExpenseAttachment.objects.get()
        self.assertEqual(att.original_name, "evil name.jpeg")
        self.assertTrue(att.file.name.startswith("expense-attachments/"))
        self.assertNotIn("evil", att.file.name)
        self.assertTrue(att.file.name.endswith(".jpg"))

    def test_unsupported_extension_is_refused(self):
        for bad in (SimpleUploadedFile("tool.exe", b"MZ\x90\x00" + b"\x00" * 30), SimpleUploadedFile("page.html", b"<html>"),
                    SimpleUploadedFile("pic.gif", b"GIF89a" + b"\x00" * 20)):
            response = self.bulk(self.root, [self.entry()], files={0: [bad]})
            self.assertEqual(response.status_code, 400, bad.name)
            self.assertIn("attachments", response.json()["entries"][0]["errors"])
        self.assertFalse(Expense.objects.exists())

    def test_content_must_match_the_extension(self):
        for fake in (SimpleUploadedFile("bill.pdf", b"MZ\x90\x00 not a pdf", content_type="application/pdf"),
                     SimpleUploadedFile("bill.jpg", PDF, content_type="image/jpeg"),
                     SimpleUploadedFile("bill.png", JPEG, content_type="image/png")):
            response = self.bulk(self.root, [self.entry()], files={0: [fake]})
            self.assertEqual(response.status_code, 400, fake.name)
            self.assertIn("aren't a real", " ".join(response.json()["entries"][0]["errors"]["attachments"]))

    def test_oversized_and_too_many_files(self):
        with mock.patch.object(svc, "MAX_FILE_BYTES", 50):
            response = self.bulk(self.root, [self.entry()], files={0: [jpg()]})
        self.assertIn("larger than", response.json()["entries"][0]["errors"]["attachments"][0])
        with mock.patch.object(svc, "MAX_FILES_PER_EXPENSE", 2):
            response = self.bulk(self.root, [self.entry()], files={0: [jpg(), png(), pdf()]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Expense.objects.exists())

    def test_files_for_a_missing_entry_are_refused(self):
        response = self.bulk(self.root, [self.entry()], files={4: [jpg()]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Expense.objects.exists())

    def test_download_preview_add_and_remove(self):
        self.bulk(self.root, [self.entry()], files={0: [pdf()]})
        expense = Expense.objects.get()
        att = expense.attachments.get()
        preview = self.root.get(f"/api/expense-attachments/{att.id}/file/")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview["Content-Type"], "application/pdf")
        self.assertTrue(preview["Content-Disposition"].startswith("inline"))
        self.assertEqual(preview["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(preview.streaming_content), PDF)
        download = self.root.get(f"/api/expense-attachments/{att.id}/file/?download=1")
        self.assertTrue(download["Content-Disposition"].startswith("attachment"))
        # release the open files (Windows can't delete an open file); not
        # response.close(), which would also end the test's DB connection
        for response in (preview, download):
            for closer in response._resource_closers:
                closer()

        added = self.root.post(f"/api/expenses/{expense.id}/attachments/", {"attachments": [jpg("extra.jpg")]}, format="multipart")
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(len(added.json()["attachments"]), 2)
        path = att.file.path
        with self.captureOnCommitCallbacks(execute=True):
            removed = self.root.delete(f"/api/expenses/{expense.id}/attachments/{att.id}/")
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(os.path.exists(path))
        self.assertEqual([a["original_name"] for a in removed.json()["attachments"]], ["extra.jpg"])
        # audit history on the expense
        history = self.root.get(f"/api/expenses/{expense.id}/").json()["history"]
        actions = {h["action"] for h in history}
        self.assertTrue({"attachments", "attachment-removed"} <= actions, actions)

    def test_no_public_media_url(self):
        self.bulk(self.root, [self.entry()], files={0: [jpg()]})
        att = ExpenseAttachment.objects.get()
        from django.test import Client
        self.assertNotEqual(Client().get(f"/media/{att.file.name}").status_code, 200)
        self.assertIn(Client().get(f"/api/expense-attachments/{att.id}/file/").status_code, (401, 403))


class PaymentAndBooksTests(ExpenseTestBase):
    def pay_fields(self, status, method="Cash", **extra):
        return {"payment_status": status, "payment_method": method, "payment_date": self.today.isoformat(), **extra}

    def test_unpaid_posts_nothing(self):
        self.bulk(self.root, [self.entry(payment_method="Cash", payment_date=self.today.isoformat())])
        expense = Expense.objects.get()
        self.assertEqual((expense.payment_status, expense.paid_amount), ("unpaid", 0))
        self.assertFalse(ExpensePayment.objects.exists())
        self.assertFalse(CashEntry.objects.exists() or BankEntry.objects.exists())

    def test_paid_cash_posts_one_cash_out_entry(self):
        self.bulk(self.root, [self.entry(amount=1200, **self.pay_fields("paid"))])
        entry = CashEntry.objects.get()
        expense = Expense.objects.get()
        self.assertEqual((entry.type, entry.amount, entry.expense_payment.expense), (CashEntry.OUT, 1200, expense))
        self.assertEqual((expense.payment_status, expense.paid_amount, expense.outstanding), ("paid", 1200, 0))
        self.assertFalse(BankEntry.objects.exists())

    def test_partial_by_bank_then_the_rest(self):
        self.bulk(self.root, [self.entry(amount=1000, **self.pay_fields("partial", "UPI", paid_amount=400, payment_reference="UTR9"))])
        expense = Expense.objects.get()
        self.assertEqual((expense.payment_status, expense.paid_amount, expense.outstanding), ("partial", 400, 600))
        bank = BankEntry.objects.get()
        self.assertEqual((bank.type, bank.amount, bank.reference), (BankEntry.OUT, 400, "UTR9"))
        too_much = self.root.post(f"/api/expenses/{expense.id}/payments/", {"amount": 700, "payment_method": "Cash", "payment_date": self.today.isoformat()}, format="json")
        self.assertEqual(too_much.status_code, 400)
        rest = self.root.post(f"/api/expenses/{expense.id}/payments/", {"amount": 600, "payment_method": "Cash", "payment_date": self.today.isoformat()}, format="json")
        self.assertEqual(rest.status_code, 201, rest.content)
        self.assertEqual(rest.json()["payment_status"], "paid")
        self.assertEqual((BankEntry.objects.count(), CashEntry.objects.count()), (1, 1))

    def test_partial_needs_an_amount_below_the_bill(self):
        response = self.bulk(self.root, [self.entry(amount=500, **self.pay_fields("partial", paid_amount=500))])
        self.assertIn("paid_amount", response.json()["entries"][0]["errors"])
        response = self.bulk(self.root, [self.entry(payment_status="paid")])
        self.assertTrue({"payment_method", "payment_date"} <= set(response.json()["entries"][0]["errors"]))

    def test_posted_entries_are_locked_and_scoped(self):
        self.bulk(self.root, [self.entry(**self.pay_fields("paid"))])
        entry = CashEntry.objects.get()
        response = self.root.patch(f"/api/cash-entries/{entry.id}/", {"amount": 1}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("EXP-", response.json()["detail"])
        listed = self.root.get("/api/cash-entries/").json()
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertTrue(rows[0]["invoice_code"].startswith("EXP-"))
        # store-assigned cash book viewers see their store's expense payments only
        kb_viewer = client_for(make_user("kb-cash", ["cashbook.view"], stock_point=self.kb))
        np_viewer = client_for(make_user("np-cash", ["cashbook.view"], stock_point=self.np))
        count = lambda c: len(c.get("/api/cash-entries/").json().get("results", []))  # noqa: E731
        self.assertEqual((count(kb_viewer), count(np_viewer)), (1, 0))

    def test_cancel_reverses_payments_without_changing_history(self):
        self.bulk(self.root, [self.entry(amount=800, **self.pay_fields("paid", "Bank transfer", payment_reference="NEFT1"))])
        expense = Expense.objects.get()
        original = BankEntry.objects.get()
        self.assertEqual(self.root.post(f"/api/expenses/{expense.id}/cancel/", {}, format="json").status_code, 400)
        response = self.root.post(f"/api/expenses/{expense.id}/cancel/", {"reason": "Entered twice"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        entries = list(BankEntry.objects.order_by("id").values_list("id", "type", "amount"))
        self.assertEqual(entries, [(original.id, "out", 800), (entries[1][0], "in", 800)])
        original.refresh_from_db()
        self.assertEqual((original.type, original.amount, original.date), ("out", 800, self.today))
        # no second reversal, no further payments, no edits
        self.assertEqual(self.root.post(f"/api/expenses/{expense.id}/cancel/", {"reason": "again"}, format="json").status_code, 400)
        self.assertEqual(BankEntry.objects.count(), 2)
        self.assertEqual(self.root.patch(f"/api/expenses/{expense.id}/", {"amount": 5}, format="json").status_code, 400)

    def test_edit_respects_payments(self):
        self.bulk(self.root, [self.entry(amount=1000, **self.pay_fields("partial", paid_amount=600))])
        expense = Expense.objects.get()
        self.assertEqual(self.root.patch(f"/api/expenses/{expense.id}/", {"amount": 500}, format="json").status_code, 400)
        moved = self.root.patch(f"/api/expenses/{expense.id}/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(moved.status_code, 400)
        ok = self.root.patch(f"/api/expenses/{expense.id}/", {"amount": 600, "vendor": "New vendor"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual((ok.json()["payment_status"], ok.json()["vendor"]), ("paid", "New vendor"))
        self.assertEqual(CashEntry.objects.get().amount, 600)  # the posted payment itself never changes
        history = ok.json()["history"]
        self.assertTrue(any(h["action"] in ("updated", "partial_update") or h["changes"] for h in history))

    def test_put_and_delete_are_not_offered(self):
        self.bulk(self.root, [self.entry()])
        expense = Expense.objects.get()
        self.assertEqual(self.root.delete(f"/api/expenses/{expense.id}/").status_code, 405)
        self.assertEqual(self.root.put(f"/api/expenses/{expense.id}/", self.entry(), format="json").status_code, 405)


class ProfitLossIntegrationTests(ExpenseTestBase):
    def pl(self, store, **params):
        params = {"store": store.id, "period": "custom", "date_from": "2026-09-01", "date_to": "2026-09-30", **params}
        response = self.root.get("/api/reports/profit-loss/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_expenses_flow_into_the_right_store_and_period(self):
        sept, aug = "2026-09-10", "2026-08-31"
        self.bulk(self.root, [
            self.entry(expense_date=sept, amount=5000),  # rent, unpaid -- still an expense
            self.entry(expense_date=sept, amount=1180, gst_amount=180, gst_claimable=True, category=self.other.id,
                       payment_status="paid", payment_method="Cash", payment_date=self.today.isoformat()),
            self.entry(expense_date=sept, amount=300, gst_amount=50),  # GST not claimable: full amount
            self.entry(expense_date=aug, amount=999),  # other period
            self.entry(store=self.np, expense_date=sept, amount=777),  # other store
            self.entry(shared=True, stock_point=None, expense_date=sept, amount=2000),  # head office
        ])
        st = self.pl(self.kb)["statement"]
        self.assertEqual((st["operating_expenses"], st["other_expenses"], st["expense_count"]), (5300, 1000, 3))
        self.assertEqual(st["net_profit"], st["gross_profit"] - 6300)
        self.assertEqual(self.pl(self.np)["statement"]["operating_expenses"], 777)
        listed = self.root.get("/api/reports/profit-loss/transactions/", {"store": self.kb.id, "kind": "expenses", "period": "custom",
                                                                          "date_from": "2026-09-01", "date_to": "2026-09-30"}).json()
        self.assertEqual(sorted(r["counted"] for r in listed["results"]), [300, 1000, 5000])
        stores = self.root.get("/api/reports/profit-loss/stores/", {"period": "custom", "date_from": "2026-09-01", "date_to": "2026-09-30"}).json()
        self.assertEqual(stores["shared_expenses"]["operating_expenses"], 2000)
        self.assertEqual(stores["consolidated"]["expenses"], 6300 + 777 + 2000)
        monthly = {p["bucket"]: p for p in self.pl(self.kb)["monthly"]}
        self.assertEqual((monthly["2026-08-01"]["expenses"], monthly["2026-09-01"]["expenses"]), (999, 6300))

    def test_payment_date_does_not_move_the_expense(self):
        self.bulk(self.root, [self.entry(expense_date="2026-08-20", amount=400, payment_status="paid",
                                         payment_method="Cash", payment_date=self.today.isoformat())])
        # nothing recorded for September: unavailable, not zero
        self.assertIsNone(self.pl(self.kb)["statement"]["operating_expenses"])
        self.assertEqual(self.pl(self.kb, date_from="2026-08-01", date_to="2026-08-31")["statement"]["operating_expenses"], 400)

    def test_net_profit_only_for_months_with_expense_records(self):
        self.bulk(self.root, [self.entry(expense_date="2026-09-05", amount=900)])
        data = self.pl(self.kb)
        st = data["statement"]
        self.assertEqual((st["data_quality"]["expense_status"], st["net_profit"]), ("recorded", st["gross_profit"] - 900))
        monthly = {p["bucket"]: p for p in data["monthly"]}
        self.assertEqual(monthly["2026-09-01"]["net_profit"], -900)
        self.assertIsNone(monthly["2026-08-01"]["net_profit"])  # nothing recorded for August
        self.assertTrue(all(p["net_profit"] is not None for p in data["trend"]["points"]))

    def test_cancelled_expenses_leave_the_pl(self):
        self.bulk(self.root, [self.entry(expense_date="2026-09-05", amount=900)])
        expense = Expense.objects.get()
        self.assertEqual(self.pl(self.kb)["statement"]["operating_expenses"], 900)
        self.root.post(f"/api/expenses/{expense.id}/cancel/", {"reason": "Wrong store"}, format="json")
        st = self.pl(self.kb)["statement"]
        self.assertEqual((st["expense_count"], st["operating_expenses"]), (0, None))


class AccessTests(ExpenseTestBase):
    def setUp(self):
        super().setUp()
        self.bulk(self.root, [self.entry(amount=100), self.entry(store=self.np, amount=200), self.entry(shared=True, stock_point=None, amount=300)],
                  files={0: [jpg()], 1: [jpg()]})
        self.kb_exp, self.np_exp, self.shared_exp = Expense.objects.order_by("id")
        self.np_file = self.np_exp.attachments.get()

    def assert_denied(self, user):
        client = client_for(user)
        calls = [
            client.get("/api/expenses/"), client.get(f"/api/expenses/{self.kb_exp.id}/"),
            self.bulk(client, [self.entry()]),
            client.patch(f"/api/expenses/{self.kb_exp.id}/", {"vendor": "x"}, format="json"),
            client.post(f"/api/expenses/{self.kb_exp.id}/cancel/", {"reason": "x"}, format="json"),
            client.post(f"/api/expenses/{self.kb_exp.id}/payments/", {"amount": 1}, format="json"),
            client.post(f"/api/expenses/{self.kb_exp.id}/attachments/", {"attachments": [jpg()]}, format="multipart"),
            client.get(f"/api/expense-attachments/{self.np_file.id}/file/"),
            client.get("/api/expense-categories/"),
        ]
        self.assertEqual([c.status_code for c in calls], [403] * len(calls))
        self.assertEqual(Expense.objects.count(), 3)
        self.assertTrue(PermissionDeniedLog.objects.filter(user=user, required_perm=EXPENSE_PERM).exists())
        self.assertFalse(client.get("/api/users/me/").json()["can_manage_expenses"])

    def test_superuser_sees_everything(self):
        listed = self.root.get("/api/expenses/").json()
        self.assertEqual((listed["count"], listed["totals"]["amount"]), (3, 600))
        self.assertTrue(self.root.get("/api/users/me/").json()["can_manage_expenses"])

    def test_owner_role_admin_sees_all_including_shared(self):
        owner = client_for(make_user("owner", [EXPENSE_PERM], owner=True))
        self.assertEqual(owner.get("/api/expenses/").json()["count"], 3)
        self.assertEqual(self.bulk(owner, [self.entry(shared=True, stock_point=None)]).status_code, 201)

    def test_store_admin_limited_to_their_store(self):
        admin = client_for(make_user("kb-admin", ["roles.manage", EXPENSE_PERM], stock_point=self.kb))
        listed = admin.get("/api/expenses/").json()
        self.assertEqual([r["id"] for r in listed["results"]], [self.kb_exp.id])
        self.assertEqual(admin.get(f"/api/expenses/{self.np_exp.id}/").status_code, 404)
        self.assertEqual(admin.get(f"/api/expenses/{self.shared_exp.id}/").status_code, 404)
        self.assertEqual(admin.get(f"/api/expense-attachments/{self.np_file.id}/file/").status_code, 404)
        self.assertEqual(admin.post(f"/api/expenses/{self.np_exp.id}/cancel/", {"reason": "x"}, format="json").status_code, 404)
        self.assertEqual(admin.get("/api/expenses/", {"store": self.np.id}).json()["count"], 0)
        refused = self.bulk(admin, [self.entry(), self.entry(store=self.np)])
        self.assertEqual(refused.status_code, 400)
        self.assertEqual([e["entry"] for e in refused.json()["entries"]], [2])
        shared = self.bulk(admin, [self.entry(shared=True, stock_point=None)])
        self.assertIn("stock_point", shared.json()["entries"][0]["errors"])
        moved = admin.patch(f"/api/expenses/{self.kb_exp.id}/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(moved.status_code, 403)
        self.assertEqual(self.bulk(admin, [self.entry()]).status_code, 201)

    def test_authorised_accounts_user(self):
        accounts = client_for(accounts_user("ritu", self.kb))
        self.assertEqual(accounts.get("/api/expenses/").json()["count"], 1)
        self.assertEqual(self.bulk(accounts, [self.entry()], files={0: [pdf()]}).status_code, 201)

    def test_accounts_user_without_the_permission(self):
        self.assert_denied(accounts_user("ritu", self.kb, with_perm=False))

    def test_admin_without_the_permission(self):
        self.assert_denied(make_user("kb-admin", ["roles.manage", "cashbook.edit"], stock_point=self.kb))

    def test_ordinary_staff_are_refused_even_with_the_permission(self):
        staff = make_user("sales", ["invoices.view", "invoices.create", EXPENSE_PERM], stock_point=self.kb)
        staff.is_staff = True  # is_staff is not Admin or Accounts
        staff.save()
        self.assert_denied(staff)

    def test_unassigned_admin_reaches_nothing(self):
        admin = client_for(make_user("floating", ["roles.manage", EXPENSE_PERM]))
        self.assertEqual(admin.get("/api/expenses/").json()["count"], 0)
        self.assertEqual(self.bulk(admin, [self.entry()]).status_code, 400)

    def test_anonymous(self):
        from rest_framework.test import APIClient
        client = APIClient()
        self.assertIn(client.get("/api/expenses/").status_code, (401, 403))
        self.assertIn(client.get(f"/api/expense-attachments/{self.np_file.id}/file/").status_code, (401, 403))

    def test_list_filters_search_and_sort(self):
        r = lambda **p: self.root.get("/api/expenses/", p).json()  # noqa: E731
        self.assertEqual(r(store="shared")["count"], 1)
        self.assertEqual(r(store=self.np.id)["results"][0]["id"], self.np_exp.id)
        self.assertEqual(r(q=self.kb_exp.code)["results"][0]["id"], self.kb_exp.id)
        self.assertEqual([x["amount"] for x in r(sort="amount")["results"]], [100, 200, 300])
        self.assertEqual(r(payment_status="paid")["count"], 0)
        self.assertEqual(r(category=self.other.id)["count"], 0)
        self.assertEqual(r(date_from=(self.today + timedelta(days=1)).isoformat())["count"], 0)
        self.assertEqual(self.root.get("/api/expenses/", {"date_from": "nope"}).status_code, 400)

    def test_audit_history_records_creation(self):
        detail = self.root.get(f"/api/expenses/{self.kb_exp.id}/").json()
        self.assertEqual(detail["created_by_name"], "root")
        self.assertTrue(ActivityLog.objects.filter(record_type="accounting.expense", record_id=str(self.kb_exp.id)).exists())

    def test_migration_grants_owner_admin_and_accounts_roles(self):
        import importlib

        from django.apps import apps
        migration = importlib.import_module("accounts.migrations.0011_expenses_permission")
        for slug in ("owner", "manager", "accountant", "sales"):
            Role.objects.get_or_create(slug=slug, defaults={"label": slug})
        migration.add_permission(apps, None)
        granted = set(Permission.objects.get(codename=EXPENSE_PERM).roles.values_list("slug", flat=True))
        self.assertEqual(granted & {"owner", "manager", "accountant", "sales"}, {"owner", "manager", "accountant"})


def setUpModule():
    os.makedirs(TMP_MEDIA, exist_ok=True)


class ModelAndMigrationTests(ExpenseTestBase):
    def test_model_creation_and_derived_amounts(self):
        expense = Expense.objects.create(stock_point=self.kb, category=self.rent, expense_date=self.today, amount=1180,
                                         gst_amount=180, gst_claimable=True, vendor="Landlord", created_by=self.superuser)
        self.assertEqual(expense.code, f"EXP-{expense.pk:05d}")
        self.assertEqual((expense.recognised_amount, expense.outstanding, expense.payment_status, expense.status), (1000, 1180, "unpaid", "active"))
        self.assertIsNotNone(expense.created_at)
        expense.gst_claimable = False
        self.assertEqual(expense.recognised_amount, 1180)

    def test_database_refuses_impossible_amounts(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Expense.objects.create(stock_point=self.kb, category=self.rent, expense_date=self.today, amount=100,
                                   gst_amount=200, created_by=self.superuser)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Expense.objects.create(stock_point=self.kb, category=self.rent, expense_date=self.today, amount=100,
                                   paid_amount=150, created_by=self.superuser)

    def test_tables_exist_after_migrating(self):
        from django.db import connection
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            cash_columns = {c.name for c in connection.introspection.get_table_description(cursor, "accounting_cashentry")}
        self.assertTrue({"accounting_expense", "accounting_expensecategory", "accounting_expensepayment",
                         "accounting_expenseattachment", "accounting_expensebatch"} <= tables)
        self.assertTrue({"expense_payment_id", "expense_reversal_id"} <= cash_columns)

    def test_expense_migration_only_adds(self):
        """0005 creates tables and adds nullable columns -- it never drops,
        renames or alters anything that already holds data."""
        import importlib

        from django.db import migrations as m
        migration = importlib.import_module("accounting.migrations.0005_expenses").Migration
        self.assertIn(("accounting", "0004_refund_postings"), migration.dependencies)
        allowed = (m.CreateModel, m.AddField, m.AddIndex, m.AddConstraint)
        for op in migration.operations:
            self.assertIsInstance(op, allowed, op)
            if isinstance(op, m.AddField) and op.model_name in ("cashentry", "bankentry"):
                self.assertTrue(op.field.null, op.name)

    def test_migrations_are_complete(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("makemigrations", "accounting", "accounts", "--check", "--dry-run", stdout=out)
        self.assertIn("No changes detected", out.getvalue())
