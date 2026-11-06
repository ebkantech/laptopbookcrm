from datetime import date, timedelta

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import StaffNotification
from crmbook_backend.testing import client_for, make_user
from rentals.billing import send_due_rent_invoices
from subscriptions import catalog, services
from subscriptions.models import Package, PackagePrice, Subscription

EXPECTED = {
    "starter": {1: 0, 3: 0, 6: 2999, 12: 4999},
    "service": {1: 999, 3: 2499, 6: 3999, 12: 5999},
    "rental": {1: 999, 3: 2499, 6: 3999, 12: 5999},
    "full": {1: 1999, 3: 3999, 6: 5999, 12: 10999},
}


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def plan(self, key, months=1, ends_on=None):
        with self.captureOnCommitCallbacks(execute=True):
            row = services.activate(key, months)
        if ends_on:
            Subscription.objects.filter(pk=row.pk).update(ends_on=ends_on)
            services.clear_cache()
        return row


class CatalogTests(TestCase):
    def test_choosing_a_module_brings_what_it_needs(self):
        self.assertEqual(catalog.with_dependencies(["rentals"]), ["inventory", "invoices", "rentals"])
        self.assertIn("repairs", catalog.with_dependencies(["leads"]))
        self.assertIn("repairs", catalog.with_dependencies(["warranty"]))

    def test_portal_needs_repairs_or_rentals(self):
        with self.assertRaises(ValidationError):
            catalog.with_dependencies(["portal"])
        self.assertIn("portal", catalog.with_dependencies(["portal", "rentals"]))

    def test_cannot_remove_what_another_module_needs(self):
        chosen = catalog.with_dependencies(["warranty", "leads"])
        self.assertEqual(catalog.dependents("repairs", chosen), ["leads", "warranty"])
        self.assertEqual(catalog.dependents("warranty", chosen), [])

    def test_portal_survives_while_one_option_remains(self):
        chosen = catalog.with_dependencies(["portal", "rentals", "repairs"])
        self.assertNotIn("portal", catalog.dependents("rentals", chosen))
        self.assertIn("portal", catalog.dependents("rentals", set(chosen) - {"repairs"}))

    def test_unknown_module_is_refused(self):
        with self.assertRaises(ValidationError):
            catalog.with_dependencies(["nonsense"])

    def test_every_blocked_module_is_a_known_one(self):
        self.assertLessEqual(set(catalog.API_PREFIXES), set(catalog.DEPENDS))
        self.assertEqual(set(catalog.API_PREFIXES), set(catalog.PERMISSION_PREFIXES))


class PriceTests(Base):
    def test_prices_match_the_price_list(self):
        found = {key: {} for key in EXPECTED}
        for price in PackagePrice.objects.select_related("package"):
            found[price.package.key][price.months] = price.amount
        self.assertEqual(found, EXPECTED)

    def test_every_package_is_dependency_complete(self):
        for package in Package.objects.all():
            self.assertEqual(sorted(package.modules), catalog.with_dependencies(package.modules), package.key)

    def test_full_has_every_module(self):
        self.assertEqual(set(Package.objects.get(key="full").modules), set(catalog.DEPENDS))

    def test_saving_a_package_adds_dependencies(self):
        package = Package.objects.create(key="x", name="X", modules=["warranty"])
        self.assertIn("repairs", package.modules)


class ActivationTests(Base):
    def test_activation_sets_the_end_date(self):
        row = self.plan("rental", 6)
        self.assertEqual((row.amount, row.months), (3999, 6))
        self.assertGreater(row.ends_on, row.starts_on + timedelta(days=170))

    def test_early_renewal_keeps_the_days_left(self):
        first = self.plan("rental", 1)
        second = self.plan("rental", 1)
        self.assertEqual(Subscription.objects.count(), 1)
        self.assertGreater(second.ends_on, first.ends_on + timedelta(days=20))

    def test_changing_package_starts_today(self):
        self.plan("rental", 12)
        row = self.plan("service", 1)
        self.assertLess(row.ends_on, date.today() + timedelta(days=40))

    def test_free_starter(self):
        self.assertEqual(self.plan("starter", 3).amount, 0)


class BlockTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = client_for(make_user("sa", superuser=True))

    def test_no_plan_limits_nothing(self):
        self.assertEqual(self.admin.get("/api/rentals/").status_code, 200)

    def test_module_outside_the_plan_is_refused_even_for_super_admin(self):
        self.plan("service")
        response = self.admin.get("/api/rentals/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "module_not_in_plan")
        self.assertEqual(self.admin.get("/api/tickets/").status_code, 200)

    def test_public_approval_pages_are_covered(self):
        self.plan("service")
        self.assertEqual(APIClient().get("/api/public/rental-approvals/abc/").status_code, 403)

    def test_full_opens_everything(self):
        self.plan("full")
        for path in ("/api/rentals/", "/api/tickets/", "/api/leads/", "/api/warranties/"):
            self.assertEqual(self.admin.get(path).status_code, 200, path)

    def test_grace_keeps_working(self):
        self.plan("full", ends_on=date.today() - timedelta(days=3))
        self.assertEqual(services.state(), services.GRACE)
        self.assertNotEqual(self.admin.post("/api/parties/", {}, format="json").status_code, 403)

    def test_read_only_refuses_writes_and_keeps_reading(self):
        self.plan("full", ends_on=date.today() - timedelta(days=8))
        self.assertEqual(services.state(), services.READ_ONLY)
        self.assertEqual(self.admin.get("/api/parties/").status_code, 200)
        response = self.admin.post("/api/parties/", {}, format="json")
        self.assertEqual(response.json()["code"], "subscription_read_only")

    def test_sign_in_still_works_when_read_only(self):
        self.plan("full", ends_on=date.today() - timedelta(days=8))
        response = APIClient().post("/api/auth/token/", {"username": "x", "password": "y"}, format="json")
        self.assertNotEqual(response.status_code, 403)

    def test_webhooks_are_not_blocked(self):
        self.plan("service", ends_on=date.today() - timedelta(days=8))
        response = APIClient().post("/api/whatsapp/meta-webhook/", {}, format="json")
        self.assertNotIn(b"subscription", response.content)

    def test_session_hides_the_blocked_permissions(self):
        self.plan("service")
        data = self.admin.get("/api/users/me/").json()["subscription"]
        self.assertIn("rentals", data["blocked_prefixes"])
        self.assertNotIn("repairs", data["blocked_prefixes"])

    def test_plan_list_for_staff(self):
        names = [plan["key"] for plan in self.admin.get("/api/subscription/").json()["plans"]]
        self.assertEqual(names, ["starter", "service", "rental", "full"])
        self.assertIn(APIClient().get("/api/subscription/").status_code, (401, 403))


class JobTests(Base):
    def test_background_jobs_stop_with_the_module(self):
        self.plan("service")
        self.assertFalse(services.can_write("rentals"))
        self.assertEqual(send_due_rent_invoices()["raised"], [])

    def test_jobs_stop_when_read_only(self):
        self.plan("full", ends_on=date.today() - timedelta(days=8))
        self.assertFalse(services.can_write("rentals"))

    def test_reminder_goes_once(self):
        make_user("sa", superuser=True)
        self.plan("full", ends_on=date.today() + timedelta(days=3))
        self.assertEqual(services.check_expiry(), ["remind-3"])
        self.assertEqual(services.check_expiry(), [])
        self.assertEqual(StaffNotification.objects.count(), 1)

    def test_nothing_early(self):
        self.plan("full", ends_on=date.today() + timedelta(days=20))
        self.assertEqual(services.check_expiry(), [])

    def test_each_stage_notifies(self):
        row = self.plan("full", ends_on=date.today() + timedelta(days=7))
        self.assertEqual(services.check_expiry(), ["remind-7"])
        self.assertEqual(services.check_expiry(date.today() + timedelta(days=7)), ["remind-grace"])
        self.assertEqual(services.check_expiry(date.today() + timedelta(days=14)), ["remind-read-only"])
        self.assertEqual(row.events.filter(key__startswith="remind-").count(), 3)

    def test_renewing_clears_old_reminders(self):
        self.plan("full", ends_on=date.today() + timedelta(days=3))
        services.check_expiry()
        row = self.plan("full", 1)
        self.assertFalse(row.events.filter(key__startswith="remind-").exists())
