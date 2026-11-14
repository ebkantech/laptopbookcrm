"""
notify_staff()/notify_user() only fire once the caller's transaction commits.

TransactionTestCase on purpose: TestCase wraps every test in a transaction
that is never committed, so it can't show the real commit / rollback /
no-transaction behaviour these tests are about. Every channel is mocked or
local -- nothing is sent anywhere.
"""
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TransactionTestCase

from accounts.models import NotificationRule, Role, StaffNotification
from crmbook_backend import notify
from crmbook_backend.testing import make_user


class Boom(Exception):
    pass


class NotifyTransactionTests(TransactionTestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.bob.role = self.alice.role
        self.bob.save(update_fields=["role"])
        for user, phone, email in ((self.alice, "9876500001", "alice@example.com"), (self.bob, "9876500002", "bob@example.com")):
            user.phone, user.email = phone, email
            user.save(update_fields=["phone", "email"])
        NotificationRule.objects.create(event_key="payment_received", role=self.alice.role,
                                        via_email=True, via_whatsapp=True, via_inapp=True)
        self.email = self.patch("crmbook_backend.notify.send_email")
        self.whatsapp = self.patch("crmbook_backend.notify.send_whatsapp")

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def inbox(self, user=None):
        rows = StaffNotification.objects.order_by("id")
        if user is not None:
            rows = rows.filter(user=user)
        return list(rows.values_list("user__username", "event_key", "subject", "body"))

    # ------------------------------------------------------------ notify_staff

    def test_sent_only_after_commit(self):
        with transaction.atomic():
            notify.notify_staff("payment_received", "Invoice INV-1 settled", "Paid in full.")
            self.email.assert_not_called()
            self.whatsapp.assert_not_called()
            self.assertEqual(self.inbox(), [])
        # same recipients, channels, event key and text as before the change
        self.assertEqual(sorted(c.args for c in self.email.call_args_list), [
            ("alice@example.com", "Invoice INV-1 settled", "Paid in full."),
            ("bob@example.com", "Invoice INV-1 settled", "Paid in full."),
        ])
        self.assertEqual(sorted(c.args for c in self.whatsapp.call_args_list),
                         [("9876500001", "Paid in full."), ("9876500002", "Paid in full.")])
        self.assertEqual(sorted(self.inbox()), [
            ("alice", "payment_received", "Invoice INV-1 settled", "Paid in full."),
            ("bob", "payment_received", "Invoice INV-1 settled", "Paid in full."),
        ])

    def test_nothing_sent_on_rollback(self):
        with self.assertRaises(Boom):
            with transaction.atomic():
                notify.notify_staff("payment_received", "Invoice INV-1 settled", "Paid in full.")
                raise Boom()
        self.email.assert_not_called()
        self.whatsapp.assert_not_called()
        self.assertEqual(self.inbox(), [])

    def test_rolled_back_savepoint_drops_only_its_own_alert(self):
        with transaction.atomic():
            notify.notify_staff("payment_received", "kept", "outer")
            try:
                with transaction.atomic():
                    notify.notify_staff("payment_received", "dropped", "inner")
                    raise Boom()
            except Boom:
                pass
        self.assertEqual({row[2] for row in self.inbox()}, {"kept"})

    def test_outside_a_transaction_it_sends_immediately(self):
        notify.notify_staff("payment_received", "Invoice INV-1 settled", "Paid in full.")
        self.assertEqual(self.email.call_count, 2)
        self.assertEqual(self.whatsapp.call_count, 2)
        self.assertEqual(len(self.inbox()), 2)

    def test_alert_db_failure_does_not_undo_the_business_change(self):
        with mock.patch("crmbook_backend.notify._create_inapp", side_effect=DatabaseError("bell table down")), \
                self.assertLogs("crmbook.notify", level="ERROR"):
            with transaction.atomic():
                Role.objects.create(slug="saved-by-the-action", label="Business change")
                notify.notify_staff("payment_received", "Invoice INV-1 settled", "Paid in full.")
        self.assertTrue(Role.objects.filter(slug="saved-by-the-action").exists())
        self.assertEqual(self.email.call_count, 2)  # other channels still went out

    def test_unexpected_crash_after_commit_is_logged_not_raised(self):
        with mock.patch("crmbook_backend.notify._notify_staff_now", side_effect=RuntimeError("bug")), \
                self.assertLogs("crmbook.notify", level="ERROR") as logs:
            with transaction.atomic():
                Role.objects.create(slug="still-saved", label="Business change")
                notify.notify_staff("payment_received", "s", "b")
        self.assertTrue(Role.objects.filter(slug="still-saved").exists())
        self.assertIn("alert failed after commit", "\n".join(logs.output))

    def test_one_recipient_failing_does_not_block_the_others(self):
        real_create = notify._create_inapp

        def create(user, *args):
            if user.pk == self.alice.pk:
                raise DatabaseError("alice's row failed")
            return real_create(user, *args)

        def email(to, *args):
            if to == "alice@example.com":
                raise RuntimeError("smtp")
            return {"status": "sent"}

        self.email.side_effect = email
        with mock.patch("crmbook_backend.notify._create_inapp", side_effect=create), \
                self.assertLogs("crmbook.notify", level="ERROR"):
            with transaction.atomic():
                notify.notify_staff("payment_received", "Invoice INV-1 settled", "Paid in full.")
        self.assertEqual([row[0] for row in self.inbox()], ["bob"])
        # alice's email and bell failed, but her WhatsApp still went, and bob got everything
        self.assertEqual(sorted(c.args[0] for c in self.whatsapp.call_args_list), ["9876500001", "9876500002"])
        self.assertIn("bob@example.com", [c.args[0] for c in self.email.call_args_list])

    # ------------------------------------------------------------- notify_user

    def test_notify_user_waits_for_commit_and_keeps_its_content(self):
        with transaction.atomic():
            notify.notify_user(self.alice, "lead_assigned", "New on-site job LD-1 -- Ravi", "12 MG Road")
            self.assertEqual(self.inbox(), [])
            self.whatsapp.assert_not_called()
        self.assertEqual(self.inbox(), [("alice", "lead_assigned", "New on-site job LD-1 -- Ravi", "12 MG Road")])
        self.whatsapp.assert_called_once_with("9876500001", "New on-site job LD-1 -- Ravi\n12 MG Road")

    def test_notify_user_nothing_on_rollback(self):
        with self.assertRaises(Boom):
            with transaction.atomic():
                notify.notify_user(self.alice, "lead_assigned", "s", "b")
                raise Boom()
        self.assertEqual(self.inbox(), [])
        self.whatsapp.assert_not_called()

    def test_notify_user_immediate_outside_a_transaction(self):
        notify.notify_user(self.alice, "lead_progress", "x" * 250, "b", whatsapp=False)
        self.assertEqual(len(self.inbox(self.alice)), 1)
        self.assertEqual(len(self.inbox()[0][2]), 200)  # subject still trimmed to the column
        self.whatsapp.assert_not_called()

    def test_notify_user_bell_failure_still_sends_whatsapp(self):
        with mock.patch("crmbook_backend.notify._create_inapp", side_effect=DatabaseError("down")), \
                self.assertLogs("crmbook.notify", level="ERROR"):
            notify.notify_user(self.alice, "lead_progress", "s", "b")
        self.whatsapp.assert_called_once()

    def test_inactive_or_missing_user_is_skipped(self):
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])
        notify.notify_user(self.bob, "lead_progress", "s", "b")
        notify.notify_user(None, "lead_progress", "s", "b")
        self.assertEqual(self.inbox(), [])
