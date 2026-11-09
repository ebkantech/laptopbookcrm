"""The printed rental agreement follows the business's own contract layout."""
from datetime import date

from django.test import TestCase, override_settings

from catalog.models import Product, StockPoint, Variant
from parties.models import Party
from rentals.documents import _device_rows, render_agreement_pdf, terms
from rentals.models import Rental, RentalAsset, RentalLine


@override_settings(BUSINESS_NAME="Royal Computer Solution", BUSINESS_ADDRESS="Shop No.-14, Babu Complex, Sector-27, Noida")
class AgreementDocumentTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="rcs", name="Noida", kind=StockPoint.SHOP)
        product = Product.objects.create(model_name="Latitude 5420", brand="Dell", product_code="P-AG",
                                         specs={"processor": "Intel Core i5", "generation": "11th Gen", "ram": "16GB", "storage": "512GB SSD"})
        variant = Variant.objects.create(product=product, code="V-AG", spec="16GB / 512GB SSD", mrp=60000, sell_price=55000, cost=41000)
        self.asset = RentalAsset.objects.create(asset_tag="AST-AG", serial_number="SN-AG-1", brand="Dell", model_name="Latitude 5420",
                                                variant=variant, source_stock_point=self.shop, purchase_price=42000)
        party = Party.objects.create(name="Verma Associates", type=Party.RENTAL, phone="9412818037", city="Noida", joined=date(2026, 1, 1))
        self.rental = Rental.objects.create(party=party, agreement_code="RNT-AG", product_label="1 device", monthly_fee=900,
                                            start=date(2026, 6, 4), tenure_months=12, last_payment=date(2026, 6, 4),
                                            terms="Customer to keep the system indoors.")
        self.line = RentalLine.objects.create(rental=self.rental, asset=self.asset, monthly_fee=900, accessories=[{"name": "Charger"}])

    def test_terms_carry_the_business_name(self):
        clauses = terms("Royal Computer Solution")
        self.assertEqual(len(clauses), 10)
        self.assertIn("remain the property of Royal Computer Solution", clauses[3])

    def test_system_detail_comes_from_the_device_and_its_product(self):
        rows = dict(_device_rows(self.line))
        self.assertEqual(rows["Processor"], "Intel Core i5 11th Gen")
        self.assertEqual(rows["RAM"], "16GB")
        self.assertEqual(rows["Others / accessories"], "Charger")
        self.assertEqual(rows["Worth (in Rupees)"], "Rs 42,000/- / unit")
        self.assertEqual(rows["Branded"], "Yes (Dell)")

    def test_the_pdf_renders_two_pages(self):
        pdf = render_agreement_pdf(self.rental)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page "), 2)
