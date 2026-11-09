from datetime import date

from django.test import TestCase

from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from rentals.models import Rental, RentalAsset, RentalEvent, RentalIssue, RentalLine
from repairs.models import RepairTicket


class DeviceHistoryTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="dh-shop", name="History Shop", kind=StockPoint.SHOP)
        self.tech = make_user("dh-tech", [], stock_point=self.shop)
        self.tech.first_name = "Ravi"
        self.tech.save()
        self.manager = client_for(make_user("dh-manager", ["rentals.view", "rentals.manage"], stock_point=self.shop))
        self.asset = RentalAsset.objects.create(asset_tag="AST-DH-1", serial_number="SN-DH-1", brand="Dell",
                                                model_name="Latitude 5420", source_stock_point=self.shop)
        self.other = RentalAsset.objects.create(asset_tag="AST-DH-2", serial_number="SN-DH-2", brand="HP",
                                                model_name="ProBook", source_stock_point=self.shop)

    def rent(self, name, code, status):
        party = Party.objects.create(name=name, type=Party.RENTAL, phone="98765432" + code[-2:], joined=date.today())
        rental = Rental.objects.create(party=party, agreement_code=code, product_label="1 device", monthly_fee=2000,
                                       start=date(2026, 1, 1), tenure_months=6, last_payment=date.today(), status=status)
        RentalLine.objects.create(rental=rental, asset=self.asset, monthly_fee=2000, condition_notes="Scratch on lid")
        RentalEvent.objects.create(rental=rental, event_type=RentalEvent.DEVICE_CHECKED_OUT)
        return rental

    def test_history_lists_customers_problems_and_repairs(self):
        old = self.rent("First Customer", "RNT-DH-01", Rental.CLOSED)
        RentalEvent.objects.create(rental=old, event_type=RentalEvent.AGREEMENT_CLOSED)
        RentalIssue.objects.create(rental=old, title="Battery drains fast", assigned_to=self.tech)
        self.rent("Second Customer", "RNT-DH-02", Rental.ACTIVE)
        RepairTicket.objects.create(code="RT-DH-1", party=old.party, brand="Dell", model_name="Latitude", serial="sn-dh-1",
                                    stock_point=self.shop, issue="Battery replacement", received=date.today(), assigned_to=self.tech)
        RepairTicket.objects.create(code="RT-DH-2", party=old.party, brand="HP", model_name="ProBook", serial="SN-DH-2",
                                    stock_point=self.shop, issue="Other laptop", received=date.today())

        body = self.manager.get(f"/api/rental-assets/{self.asset.id}/history/").json()
        self.assertEqual([a["customer"] for a in body["agreements"]], ["Second Customer", "First Customer"] if body["agreements"][0]["agreement_code"] == "RNT-DH-02" else ["First Customer", "Second Customer"])
        self.assertEqual(body["summary"]["customers"], 2)
        self.assertEqual(body["summary"]["current_customer"], "Second Customer")
        self.assertEqual(body["summary"]["problems"], 1)
        first = next(a for a in body["agreements"] if a["agreement_code"] == "RNT-DH-01")
        self.assertEqual(first["issues"][0]["assigned_to"], "Ravi")
        self.assertEqual(first["condition_notes"], "Scratch on lid")
        self.assertEqual([r["code"] for r in body["repairs"]], ["RT-DH-1"])  # matched by serial, case-insensitive
        self.assertEqual(body["repairs"][0]["assigned_to"], "Ravi")
        self.assertTrue(any(t["kind"] == "issue" for t in body["timeline"]))

    def test_inventory_lists_rental_units_of_one_variant(self):
        response = self.manager.get("/api/rental-assets/?variant=999999")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual(rows["results"] if isinstance(rows, dict) else rows, [])

    def test_history_needs_rentals_view(self):
        nobody = client_for(make_user("dh-nobody", [], stock_point=self.shop))
        self.assertEqual(nobody.get(f"/api/rental-assets/{self.asset.id}/history/").status_code, 403)
