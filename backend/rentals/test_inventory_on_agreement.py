"""
A laptop picked from Inventory on the New Agreement form leaves sale stock
only when the agreement is saved -- in the same transaction, so a refused or
failed agreement takes nothing.
"""
from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from catalog.models import Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user, verify_kyc
from parties.models import Party

from .models import Rental, RentalAsset, RentalEvent

URL = "/api/rentals/create-agreement/"


class InventoryOnAgreementTests(APITestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="inv-shop", name="Inv Shop", kind=StockPoint.SHOP)
        self.other_shop = StockPoint.objects.create(slug="inv-other", name="Other Shop", kind=StockPoint.SHOP)
        self.user = make_user("inv-staff", perms=("rentals.view", "rentals.manage", "parties.view", "parties.manage"), stock_point=self.shop)
        self.client = client_for(self.user)
        self.party = Party.objects.create(name="Ravi", type=Party.RENTAL, phone="9876543210", email="r@example.com", joined=timezone.localdate())
        verify_kyc(self.party, self.user)
        product = Product.objects.create(brand="Dell", model_name="Latitude 5420", product_code="VC-LAP-0900", category=Product.LAPTOP)
        self.variant = Variant.objects.create(product=product, code="VC-SKU-0900", spec="i5 / 16GB", mrp=1, sell_price=50000, cost=1)
        self.stock = Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=2)

    def body(self, *lines, **extra):
        return {"party": self.party.pk, "start": timezone.localdate().isoformat(), "tenure_months": 6,
                "payment_interval_months": 1, "lines": list(lines), **extra}

    def pick(self, serial="SN-INV-1", stock=None, fee=2500, tag=""):
        return {"from_inventory": {"stock": (stock or self.stock).pk, "serial_number": serial, "asset_tag": tag}, "monthly_fee": fee}

    def quantity(self, stock=None):
        return Stock.objects.get(pk=(stock or self.stock).pk).quantity

    def test_saved_agreement_takes_exactly_one_unit_and_links_the_asset(self):
        response = self.client.post(URL, self.body(self.pick()), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.quantity(), 1)
        asset = RentalAsset.objects.get(serial_number="SN-INV-1")
        self.assertEqual((asset.status, asset.variant_id, asset.source_stock_point_id), (RentalAsset.RESERVED, self.variant.pk, self.shop.pk))
        rental = Rental.objects.get(pk=response.json()["id"])
        self.assertEqual(list(rental.lines.values_list("asset_id", "monthly_fee")), [(asset.pk, 2500)])
        event = RentalEvent.objects.get(rental=rental, event_type=RentalEvent.AGREEMENT_CREATED)
        self.assertEqual(event.metadata["from_inventory"], [asset.asset_tag])

    def test_mixed_with_an_existing_rental_device(self):
        existing = RentalAsset.objects.create(asset_tag="AST-0001", serial_number="SN-OLD", brand="HP", model_name="840", source_stock_point=self.shop)
        response = self.client.post(URL, self.body({"asset_id": existing.pk, "monthly_fee": 1000}, self.pick()), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.quantity(), 1)
        self.assertEqual(Rental.objects.get().lines.count(), 2)

    def test_invalid_agreement_takes_nothing(self):
        bad = self.client.post(URL, self.body(self.pick(), tenure_months=0), format="json")
        self.assertEqual(bad.status_code, 400)
        unverified = Party.objects.create(name="No KYC", type=Party.RENTAL, phone="9876500001", joined=timezone.localdate())
        no_kyc = self.client.post(URL, {**self.body(self.pick()), "party": unverified.pk}, format="json")
        self.assertEqual(no_kyc.status_code, 400, no_kyc.content)
        self.assertEqual((self.quantity(), RentalAsset.objects.count(), Rental.objects.count()), (2, 0, 0))

    def test_zero_quantity_is_refused(self):
        Stock.objects.filter(pk=self.stock.pk).update(quantity=0)
        response = self.client.post(URL, self.body(self.pick()), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("left in stock", response.json()["lines"][0]["asset_id"][0])
        self.assertEqual((self.quantity(), RentalAsset.objects.count(), Rental.objects.count()), (0, 0, 0))

    def test_failure_after_the_unit_was_taken_rolls_everything_back(self):
        # two units asked from a shelf holding one: the first is taken, the
        # second fails inside the transaction -- nothing may stick
        Stock.objects.filter(pk=self.stock.pk).update(quantity=1)
        response = self.client.post(URL, self.body(self.pick("SN-A"), self.pick("SN-B")), format="json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["lines"][1]["asset_id"][0][:3], "No ")
        self.assertEqual((self.quantity(), RentalAsset.objects.count(), Rental.objects.count()), (1, 0, 0))

    def test_crash_while_saving_the_agreement_rolls_back_stock(self):
        with mock.patch("rentals.views.onboarding.ensure_invoices", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(URL, self.body(self.pick()), format="json")
        self.assertEqual((self.quantity(), RentalAsset.objects.count(), Rental.objects.count()), (2, 0, 0))

    def test_repeated_submission_takes_stock_once(self):
        first = self.client.post(URL, self.body(self.pick()), format="json")
        second = self.client.post(URL, self.body(self.pick()), format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 400))
        self.assertIn("already", second.json()["lines"][0]["asset_id"][0])
        self.assertEqual((self.quantity(), RentalAsset.objects.count(), Rental.objects.count()), (1, 1, 1))

    def test_same_serial_twice_in_one_agreement(self):
        response = self.client.post(URL, self.body(self.pick("SN-X"), self.pick("sn-x")), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual((self.quantity(), RentalAsset.objects.count()), (2, 0))

    def test_line_needs_exactly_one_device_source(self):
        existing = RentalAsset.objects.create(asset_tag="AST-0002", serial_number="SN-OLD2", brand="HP", model_name="840", source_stock_point=self.shop)
        both = {**self.pick(), "asset_id": existing.pk}
        self.assertEqual(self.client.post(URL, self.body(both), format="json").status_code, 400)
        self.assertEqual(self.client.post(URL, self.body({"monthly_fee": 100}), format="json").status_code, 400)
        self.assertEqual(self.quantity(), 2)

    def test_other_stores_stock_is_refused(self):
        theirs = Stock.objects.create(variant=self.variant, stock_point=self.other_shop, quantity=3)
        response = self.client.post(URL, self.body(self.pick(stock=theirs)), format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual((self.quantity(theirs), RentalAsset.objects.count()), (3, 0))
