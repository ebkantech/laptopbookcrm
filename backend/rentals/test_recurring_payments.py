from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from rentals import billing
from rentals.models import Rental, RentalAsset, RentalEvent, RentalLine
from sales.models import Invoice


def make_rental(start, tenure=12, interval=1, fees=(2000, 2500), status=Rental.ACTIVE, party=None, shop=None):
    party = party or Party.objects.create(name="Acme Rentals", type=Party.RENTAL, phone="9876543210", joined=start)
    rental = Rental.objects.create(
        party=party, product_label="Laptops", monthly_fee=sum(fees), start=start, tenure_months=tenure,
        last_payment=start, status=status, payment_interval_months=interval,
    )
    rental.agreement_code = f"RNT-{rental.pk:06d}"
    rental.save(update_fields=["agreement_code"])
    for i, fee in enumerate(fees):
        asset = RentalAsset.objects.create(asset_tag=f"A{rental.pk}-{i}", serial_number=f"S{rental.pk}-{i}", brand="Dell", model_name="5420", source_stock_point=shop)
        RentalLine.objects.create(rental=rental, asset=asset, monthly_fee=fee)
    return rental


def pay(invoice, on=None):
    invoice.status = Invoice.PAID
    invoice.paid_on = on or date.today()
    invoice.save()
    billing.on_rent_invoice_paid(invoice)


class RecurringBillingTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="shop", name="Shop", kind=StockPoint.SHOP)

    def test_invoice_covers_the_chosen_cycle(self):
        for interval in (1, 3, 6, 12):
            r = make_rental(date(2026, 1, 1), interval=interval)
            start, end = billing.next_billing_period(r)
            self.assertEqual(start, date(2026, 1, 1))
            self.assertEqual(billing.period_months(start, end), interval)
            inv = billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None)
            self.assertEqual(inv.total, 4500 * interval)
            self.assertEqual(inv.due_date, date(2026, 1, 1))
            self.assertEqual(inv.items.count(), 2)  # one line per device, qty = months
            self.assertEqual({i.qty for i in inv.items.all()}, {interval})

    def test_month_end_start_is_calendar_correct(self):
        r = make_rental(date(2026, 1, 31), interval=1)
        pay(billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None))
        r.refresh_from_db()
        self.assertEqual(billing.next_billing_period(r)[0], date(2026, 2, 28))

    def test_paying_a_quarter_counts_three_months(self):
        r = make_rental(date(2026, 1, 1), interval=3)
        pay(billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None), on=date(2026, 1, 1))
        r.refresh_from_db()
        self.assertEqual((r.months_paid, r.late_count), (3, 0))
        self.assertEqual(r.next_payment_date, date(2026, 4, 1))
        self.assertEqual(billing.next_billing_period(r)[0], date(2026, 4, 1))

    def test_late_payment_counts_once_not_per_month(self):
        r = make_rental(date(2026, 1, 1), interval=3)
        pay(billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None), on=date(2026, 1, 20))
        r.refresh_from_db()
        self.assertEqual(r.late_count, 1)

    def test_last_cycle_is_shorter_when_tenure_does_not_divide(self):
        r = make_rental(date(2026, 1, 1), tenure=10, interval=3)
        months = []
        while (period := billing.next_billing_period(r)):
            months.append(billing.period_months(*period))
            pay(billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None))
            r.refresh_from_db()
        self.assertEqual(months, [3, 3, 3, 1])
        self.assertEqual(r.months_paid, 10)
        self.assertIsNone(r.next_payment_date)
        self.assertFalse(r.next_payment_overdue)

    def test_unpaid_invoice_counts_as_billed_and_cancelled_frees_it(self):
        r = make_rental(date(2026, 1, 1), interval=6, tenure=12)
        first = billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None)
        self.assertEqual(billing.next_billing_period(r)[0], date(2026, 7, 1))
        first.status = Invoice.CANCELLED
        first.save()
        self.assertEqual(billing.next_billing_period(r)[0], date(2026, 1, 1))

    def test_quarterly_client_is_not_late_after_30_days(self):
        r = make_rental(date.today() - timedelta(days=45), interval=3)
        pay(billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None), on=r.start)
        r.refresh_from_db()
        self.assertFalse(r.next_payment_overdue)
        self.assertEqual(r.churn_score, 4)


class AutoInvoiceSchedulerTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="shop", name="Shop", kind=StockPoint.SHOP)

    def test_raises_within_lead_window_once_only(self):
        r = make_rental(date(2026, 4, 1), interval=3, status=Rental.APPROVED)
        self.assertEqual(billing.send_due_rent_invoices(today=date(2026, 3, 20))["raised"], [])  # too early
        out = billing.send_due_rent_invoices(today=date(2026, 3, 29))
        self.assertEqual(len(out["raised"]), 1)
        inv = Invoice.objects.get(code=out["raised"][0])
        self.assertEqual((inv.rental_id, inv.total, inv.period_start), (r.id, 13500, date(2026, 4, 1)))
        self.assertEqual(billing.send_due_rent_invoices(today=date(2026, 3, 30))["raised"], [])  # idempotent
        self.assertEqual(billing.send_due_rent_invoices(today=date(2026, 4, 5))["raised"], [])   # still unpaid
        self.assertEqual(Invoice.objects.filter(rental=r).count(), 1)

    def test_next_cycle_is_invoiced_after_the_first_is_paid(self):
        r = make_rental(date(2026, 4, 1), interval=3, status=Rental.APPROVED)
        pay(Invoice.objects.get(code=billing.send_due_rent_invoices(today=date(2026, 4, 1))["raised"][0]), on=date(2026, 4, 1))
        self.assertEqual(billing.send_due_rent_invoices(today=date(2026, 6, 20))["raised"], [])
        self.assertEqual(len(billing.send_due_rent_invoices(today=date(2026, 6, 29))["raised"]), 1)

    def test_skips_opted_out_inactive_and_finished_agreements(self):
        make_rental(date(2026, 4, 1), status=Rental.APPROVED).__class__.objects.update(auto_invoice=False)
        make_rental(date(2026, 4, 1), status=Rental.CLOSED)
        make_rental(date(2026, 4, 1), status=Rental.DRAFT)
        self.assertEqual(billing.send_due_rent_invoices(today=date(2026, 4, 1))["raised"], [])

    def test_uses_the_shop_of_the_previous_invoice(self):
        other = StockPoint.objects.create(slug="other", name="Other", kind=StockPoint.SHOP)
        r = make_rental(date(2026, 1, 1), interval=1, status=Rental.APPROVED)
        first = billing.raise_rent_invoice(r, stock_point=other, sent_by=None)
        pay(first)
        second = Invoice.objects.get(code=billing.send_due_rent_invoices(today=date(2026, 2, 1))["raised"][0])
        self.assertEqual(second.stock_point_id, other.id)


class PaymentPlanApiTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="shop", name="Shop", kind=StockPoint.SHOP)
        self.rental = make_rental(date(2026, 1, 1), shop=self.shop)
        self.manager = client_for(make_user("mgr", ["rentals.manage", "rentals.view"], stock_point=self.shop))
        self.viewer = client_for(make_user("viewer", ["rentals.view"], stock_point=self.shop))

    def test_change_plan_logs_event_and_validates(self):
        url = f"/api/rentals/{self.rental.id}/payment-plan/"
        self.assertEqual(self.manager.post(url, {"payment_interval_months": 4}, format="json").status_code, 400)
        res = self.manager.post(url, {"payment_interval_months": 6, "auto_invoice": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.data["payment_interval_months"], res.data["auto_invoice"]), (6, False))
        self.assertEqual(res.data["next_billing_period"]["months"], 6)
        self.assertEqual(res.data["next_billing_period"]["amount"], 27000)
        self.assertTrue(RentalEvent.objects.filter(rental=self.rental, event_type=RentalEvent.PAYMENT_PLAN_CHANGED).exists())
        self.assertEqual(self.viewer.post(url, {"payment_interval_months": 3}, format="json").status_code, 403)

    def test_ledger_lists_invoices_sent_with_dates_and_filters(self):
        self.rental.delete()
        self.rental = make_rental(date.today(), shop=self.shop)
        billing.raise_rent_invoice(self.rental, stock_point=self.shop, sent_by=None)
        other = make_rental(date.today(), party=Party.objects.create(name="Other", type=Party.RENTAL, phone="9000000000", joined=date.today()), shop=self.shop)
        billing.raise_rent_invoice(other, stock_point=self.shop, sent_by=None)
        rows = self.viewer.get("/api/rentals/payment-ledger/").data
        invoices = [r for r in rows if r["kind"] == "invoice"]
        self.assertEqual(len(invoices), 2)
        row = next(r for r in invoices if r["rental"] == self.rental.id)
        self.assertEqual((row["client_name"], row["date"], row["months"], row["total"], row["status"]),
                         ("Acme Rentals", date.today(), 1, 4500, Invoice.LINK_SENT))
        mine = self.viewer.get(f"/api/rentals/payment-ledger/?party={self.rental.party_id}").data
        self.assertEqual({r["rental"] for r in mine}, {self.rental.id})
        self.assertEqual(self.viewer.get("/api/rentals/payment-ledger/?status=Paid").data, [])
        self.assertEqual(APIClient().get("/api/rentals/payment-ledger/").status_code in (401, 403), True)

    def test_ledger_history_states_paid_late_overdue_due_and_scheduled(self):
        today = date.today()
        r = make_rental(today - timedelta(days=100), tenure=12, interval=1, status=Rental.ACTIVE, shop=self.shop)
        # month 1: due 100 days ago, paid 4 days late
        first = billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None)
        pay(first, on=r.start + timedelta(days=4))
        r.refresh_from_db()
        # month 2: due ~70 days ago, never paid -> overdue
        second = billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None)
        rows = {x["code"]: x for x in self.viewer.get(f"/api/rentals/payment-ledger/?rental={r.id}").data if x["kind"] == "invoice"}
        a, b = rows[first.code], rows[second.code]
        self.assertEqual((a["status"], a["days_late"], a["paid_on"]), (Invoice.PAID, 4, r.start + timedelta(days=4)))
        self.assertEqual(b["status"], Invoice.OVERDUE)
        self.assertGreater(b["days_overdue"], 30)
        # a rental whose invoice is not due yet
        fut = make_rental(today + timedelta(days=10), shop=self.shop)
        up = billing.raise_rent_invoice(fut, stock_point=self.shop, sent_by=None)
        row = next(x for x in self.viewer.get(f"/api/rentals/payment-ledger/?rental={fut.id}").data if x["kind"] == "invoice")
        self.assertEqual((row["status"], row["due_in_days"], row["days_overdue"]), (Invoice.LINK_SENT, 10, 0))
        # the next invoice still to be sent shows as scheduled, with the date it will go out
        sched = [x for x in self.viewer.get(f"/api/rentals/payment-ledger/?rental={r.id}").data if x["kind"] == "scheduled"]
        self.assertEqual(len(sched), 1)
        self.assertEqual(sched[0]["status"], "Scheduled")
        self.assertEqual(sched[0]["period_start"], billing.next_billing_period(r)[0])
        self.assertEqual(sched[0]["send_on"], sched[0]["period_start"] - timedelta(days=billing.INVOICE_LEAD_DAYS))
        self.assertEqual(sched[0]["total"], 4500)
        r.auto_invoice = False
        r.save()
        manual = [x for x in self.viewer.get(f"/api/rentals/payment-ledger/?rental={r.id}").data if x["kind"] == "scheduled"][0]
        self.assertIsNone(manual["send_on"])

    def test_ledger_status_filters(self):
        r = make_rental(date.today() - timedelta(days=40), tenure=6, shop=self.shop)
        paid = billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None)
        pay(paid, on=r.start)
        r.refresh_from_db()
        billing.raise_rent_invoice(r, stock_point=self.shop, sent_by=None)
        get = lambda q: self.viewer.get(f"/api/rentals/payment-ledger/?rental={r.id}&{q}").data
        self.assertEqual([x["status"] for x in get("status=Paid")], [Invoice.PAID])
        self.assertEqual([x["kind"] for x in get("status=Scheduled")], ["scheduled"])
        self.assertTrue(all(x["kind"] == "invoice" and x["status"] != Invoice.PAID for x in get("status=Overdue")))
        self.assertEqual(len(get("status=Unpaid")) + len(get("status=Overdue")), 1)
        self.assertEqual([x for x in get("from=2999-01-01") if x["kind"] == "invoice"], [])

    def test_cannot_raise_an_invoice_ahead_of_its_due_window(self):
        staff = client_for(make_user("rent-manager", ["rentals.view", "rentals.manage"], stock_point=self.shop))
        r = make_rental(date.today() - timedelta(days=1), tenure=12, interval=1, shop=self.shop)
        url = f"/api/rentals/{r.id}/raise-invoice/"
        ok = staff.post(url, {"stock_point": self.shop.id}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)           # this month is due: allowed
        again = staff.post(url, {"stock_point": self.shop.id}, format="json")
        self.assertEqual(again.status_code, 400)                      # next month is weeks away: refused
        self.assertIn("can be raised from", again.json()["detail"])
        self.assertIn("automatically", again.json()["detail"])        # auto-invoice is on
        r.refresh_from_db()
        self.assertEqual(Invoice.objects.filter(party=r.party).count(), 1)
        shown = staff.get(f"/api/rentals/{r.id}/").json()["next_billing_period"]
        self.assertFalse(shown["can_raise_now"])
        self.assertEqual(shown["raise_from"], str(billing.next_billing_period(r)[0] - timedelta(days=billing.INVOICE_LEAD_DAYS)))
        # inside the 3-day window it opens up
        soon = make_rental(date.today() + timedelta(days=2), shop=self.shop)
        self.assertTrue(staff.get(f"/api/rentals/{soon.id}/").json()["next_billing_period"]["can_raise_now"])
        self.assertEqual(staff.post(f"/api/rentals/{soon.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json").status_code, 201)
        far = make_rental(date.today() + timedelta(days=30), shop=self.shop)
        self.assertEqual(staff.post(f"/api/rentals/{far.id}/raise-invoice/", {"stock_point": self.shop.id}, format="json").status_code, 400)

    def test_renewing_a_completed_agreement_reuses_its_devices(self):
        staff = client_for(make_user("renewer", ["rentals.view", "rentals.manage"], stock_point=self.shop))
        old = make_rental(date.today() - timedelta(days=200), tenure=6, interval=3, fees=(2500, 1800), shop=self.shop)
        old.months_paid = 6
        old.save()
        RentalAsset.objects.filter(rental_lines__rental=old).update(status=RentalAsset.RENTED)
        lines = [{"asset_id": l.asset_id, "monthly_fee": l.monthly_fee} for l in old.lines.all()]
        body = {"party": old.party_id, "start": str(date.today()), "tenure_months": 12, "payment_interval_months": 6, "lines": lines}
        # without "renews" the devices are still out on rent
        self.assertEqual(staff.post("/api/rentals/create-agreement/", body, format="json").status_code, 400)
        ok = staff.post("/api/rentals/create-agreement/", {**body, "renews": old.id}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        old.refresh_from_db()
        self.assertEqual(old.status, Rental.CLOSED)
        new = Rental.objects.get(pk=ok.json()["id"])
        self.assertEqual((new.status, new.party_id, new.payment_interval_months), (Rental.DRAFT, old.party_id, 6))
        self.assertEqual({a.status for a in RentalAsset.objects.filter(rental_lines__rental=new)}, {RentalAsset.RESERVED})
        self.assertTrue(RentalEvent.objects.filter(rental=new, metadata__renews=old.agreement_code).exists())

    def test_cannot_renew_an_unfinished_or_someone_elses_agreement(self):
        staff = client_for(make_user("renewer2", ["rentals.view", "rentals.manage"], stock_point=self.shop))
        live = make_rental(date.today(), tenure=6, shop=self.shop)          # months_paid 0
        spare = RentalAsset.objects.create(asset_tag="SP1", serial_number="SP1", brand="HP", model_name="X", status=RentalAsset.AVAILABLE, source_stock_point=self.shop)
        lines = [{"asset_id": spare.id, "monthly_fee": 1000}]
        base = {"start": str(date.today()), "tenure_months": 6, "lines": lines}
        unfinished = staff.post("/api/rentals/create-agreement/", {**base, "party": live.party_id, "renews": live.id}, format="json")
        self.assertEqual(unfinished.status_code, 400)
        self.assertIn("completed", str(unfinished.json()))
        done = make_rental(date.today() - timedelta(days=300), tenure=6, shop=self.shop)
        done.months_paid = 6
        done.save()
        other = Party.objects.create(name="Someone Else", type=Party.RENTAL, phone="9000011111", joined=date.today())
        wrong = staff.post("/api/rentals/create-agreement/", {**base, "party": other.id, "renews": done.id}, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.assertIn("different customer", str(wrong.json()))
        done.refresh_from_db()
        self.assertEqual(done.status, Rental.ACTIVE)         # nothing was closed by the refused requests

    def test_store_staff_only_see_their_own_stores_ledger_and_renewals(self):
        other_shop = StockPoint.objects.create(slug="other-shop", name="Other Shop", kind=StockPoint.SHOP)
        mine = make_rental(date.today() - timedelta(days=1), shop=self.shop)
        theirs = make_rental(date.today() - timedelta(days=1), shop=other_shop,
                             party=Party.objects.create(name="Far Away Ltd", type=Party.RENTAL, phone="9111111111", joined=date.today()))
        billing.raise_rent_invoice(mine, stock_point=self.shop, sent_by=None)
        billing.raise_rent_invoice(theirs, stock_point=other_shop, sent_by=None)
        rows = self.viewer.get("/api/rentals/payment-ledger/").data      # the viewer is assigned to self.shop
        self.assertEqual({r["rental"] for r in rows if r["kind"] == "invoice"}, {mine.id})
        self.assertEqual({r["rental"] for r in rows if r["kind"] == "scheduled"}, {mine.id, self.rental.id})   # never theirs.id
        # and cannot renew another store's finished agreement
        theirs.months_paid = theirs.tenure_months
        theirs.save()
        mgr = self.manager
        spare = RentalAsset.objects.create(asset_tag="SC1", serial_number="SC1", brand="HP", model_name="X", status=RentalAsset.AVAILABLE, source_stock_point=self.shop)
        res = mgr.post("/api/rentals/create-agreement/", {"party": theirs.party_id, "start": str(date.today()), "tenure_months": 3,
                       "lines": [{"asset_id": spare.id, "monthly_fee": 1000}], "renews": theirs.id}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("isn't at your store", str(res.json()))

    def test_cron_endpoint_requires_the_token(self):
        make_rental(date.today(), status=Rental.APPROVED, shop=self.shop)
        Invoice.objects.all().delete()
        url = "/api/rentals/cron/send-due-invoices/"
        anon = APIClient()
        with self.settings():
            import os
            os.environ["RENTAL_CRON_TOKEN"] = "s3cret-for-test"
            try:
                self.assertEqual(anon.post(url).status_code, 403)
                self.assertEqual(anon.post(url, HTTP_X_CRON_TOKEN="wrong").status_code, 403)
                res = anon.post(url, HTTP_X_CRON_TOKEN="s3cret-for-test")
                self.assertEqual(res.status_code, 200)
                self.assertGreaterEqual(len(res.data["raised"]), 1)
            finally:
                del os.environ["RENTAL_CRON_TOKEN"]
        self.assertEqual(anon.post(url, HTTP_X_CRON_TOKEN="").status_code, 403)  # unset token never matches

    def test_create_agreement_accepts_interval(self):
        asset = RentalAsset.objects.create(asset_tag="NEW1", serial_number="NEWS1", brand="HP", model_name="X", source_stock_point=self.shop)
        party = Party.objects.create(name="New", type=Party.RENTAL, phone="9111111111", joined=date.today())
        body = {"party": party.id, "start": "2026-05-01", "tenure_months": 12, "payment_interval_months": 3,
                "lines": [{"asset_id": asset.id, "monthly_fee": 1500}]}
        res = self.manager.post("/api/rentals/create-agreement/", body, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["payment_interval_months"], 3)
        bad = self.manager.post("/api/rentals/create-agreement/", {**body, "payment_interval_months": 5}, format="json")
        self.assertEqual(bad.status_code, 400)


class CreateAgreementValidationTests(TestCase):
    """Server-side limits behind the agreement form -- the browser can be bypassed."""

    def setUp(self):
        self.shop = StockPoint.objects.create(slug="val-shop", name="Val Shop", kind=StockPoint.SHOP)
        self.client = client_for(make_user("mgr2", ["rentals.manage", "rentals.view"], stock_point=self.shop))
        self.party = Party.objects.create(name="Val Co", type=Party.RENTAL, phone="9876500000", joined=date.today())
        self.asset = RentalAsset.objects.create(asset_tag="V1", serial_number="VS1", brand="HP", model_name="A", source_stock_point=self.shop)
        self.asset2 = RentalAsset.objects.create(asset_tag="V2", serial_number="VS2", brand="HP", model_name="B", source_stock_point=self.shop)

    def post(self, **over):
        body = {"party": self.party.id, "start": date.today().isoformat(), "tenure_months": 6,
                "payment_interval_months": 3, "lines": [{"asset_id": self.asset.id, "monthly_fee": 1500}]}
        body.update(over)
        return self.client.post("/api/rentals/create-agreement/", body, format="json")

    def test_valid_agreement(self):
        self.assertEqual(self.post().status_code, 201)

    def test_each_bad_value_is_rejected_with_a_message_naming_the_field(self):
        cases = {
            "tenure_months": [0, -3, 121, 100000, "abc", 1.5, None],
            "party": [None, 99999],
            "start": ["", "not-a-date", "2026-02-31", "1999-01-01", "2099-01-01"],
            "payment_interval_months": [2, 0, 24, "x"],
            "terms": ["x" * 2001],
        }
        for field, values in cases.items():
            for v in values:
                res = self.post(**{field: v})
                self.assertEqual(res.status_code, 400, (field, v, res.data))
                self.assertIn(field, res.data, (field, v))
        self.assertEqual(Rental.objects.count(), 0)

    def test_line_rules(self):
        for fee in (0, -100, 1_000_001, 10**10, "abc", 1500.5, None):
            res = self.post(lines=[{"asset_id": self.asset.id, "monthly_fee": fee}])
            self.assertEqual(res.status_code, 400, (fee, res.data))
            self.assertIn("monthly_fee", res.data["lines"][0], fee)
        self.assertEqual(self.post(lines=[]).status_code, 400)
        self.assertEqual(self.post(lines=[{"asset_id": 99999, "monthly_fee": 100}]).status_code, 400)
        twice = self.post(lines=[{"asset_id": self.asset.id, "monthly_fee": 1}, {"asset_id": self.asset.id, "monthly_fee": 1}])
        self.assertEqual(twice.status_code, 400)
        self.assertIn("lines", twice.data)
        self.assertEqual(Rental.objects.count(), 0)

    def test_boundaries_accepted(self):
        self.assertEqual(self.post(tenure_months=120, lines=[{"asset_id": self.asset.id, "monthly_fee": 1_000_000}]).status_code, 201)
        self.assertEqual(self.post(tenure_months=1, payment_interval_months=12, lines=[{"asset_id": self.asset2.id, "monthly_fee": 1}]).status_code, 201)

    def test_unavailable_device_is_refused(self):
        self.assertEqual(self.post().status_code, 201)
        res = self.post()  # same asset, now reserved
        self.assertEqual(res.status_code, 400)
        self.assertIn("lines", res.data)

    def test_needs_the_manage_permission(self):
        viewer = client_for(make_user("view2", ["rentals.view"]))
        res = viewer.post("/api/rentals/create-agreement/", {"party": self.party.id}, format="json")
        self.assertEqual(res.status_code, 403)
