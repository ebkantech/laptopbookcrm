"""Real purchase costs -> real profit (catalog.costing, catalog.cost_views, reports.profit_loss)."""
from datetime import date

from django.test import TestCase

from catalog.models import Part, PartStock, Product, Stock, StockPoint, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from repairs.serializers import RepairEstimateLineSerializer, StaffRepairEstimateLineSerializer
from sales.models import Invoice, InvoiceItem
from sales.services import create_invoice

ADD = "/api/inventory/add-stock/"
REVIEW = "/api/costs/review/"
PL = "/api/reports/profit-loss/"
SEPT = {"period": "custom", "date_from": "2026-09-01", "date_to": "2026-09-30"}


class CostBase(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Buyer", type=Party.RETAIL, phone="9876543211", joined=date(2026, 1, 1))
        self.product = Product.objects.create(brand="Dell", model_name="Latitude 5440", product_code="VC-LAP-0001", category="laptop")
        self.real = Variant.objects.create(product=self.product, code="VC-SKU-0001", spec="i5 / 16GB", colour="Black",
                                           sell_price=50000, mrp=55000, cost=40000)
        self.guess = Variant.objects.create(product=self.product, code="VC-SKU-0002", spec="i7 / 32GB", colour="Black",
                                            sell_price=70000, mrp=75000, cost=54600, cost_estimated=True)
        Stock.objects.create(variant=self.real, stock_point=self.kb, quantity=3)
        Stock.objects.create(variant=self.real, stock_point=self.np, quantity=7)
        Stock.objects.create(variant=self.guess, stock_point=self.kb, quantity=2)
        self.owner = make_user("root", superuser=True)
        self.kb_admin = make_user("kb-admin", ["inventory.edit"], stock_point=self.kb)

    def sell(self, lines, day=date(2026, 9, 5), store=None, source=Invoice.SALE):
        return create_invoice(lines=lines, party=self.party, stock_point=store or self.kb, date=day,
                              status=Invoice.PAID, source=source, pay_method="Cash")

    def quality(self, store=None):
        response = client_for(self.owner).get(PL, {"store": (store or self.kb).id, **SEPT})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["statement"]


class AddStockCostTests(CostBase):
    def add(self, variant, qty, cost=None, client=None):
        body = {"entry": "existing", "product": self.product.id, "variant": variant.id, "stock_point": self.kb.id, "quantity": qty}
        if cost is not None:
            body["cost"] = cost
        return (client or client_for(self.kb_admin)).post(ADD, body, format="json")

    def test_purchase_cost_is_averaged_over_units_in_stock(self):
        # 10 units at 40,000 + 2 bought at 46,000 -> 41,000 each
        self.assertEqual(self.add(self.real, 2, cost=46000).status_code, 201)
        self.real.refresh_from_db()
        self.assertEqual((self.real.cost, self.real.cost_estimated), (41000, False))

    def test_first_real_cost_replaces_the_guess(self):
        self.assertEqual(self.add(self.guess, 1, cost=60000).status_code, 201)
        self.guess.refresh_from_db()
        self.assertEqual((self.guess.cost, self.guess.cost_estimated), (60000, False))

    def test_no_cost_given_leaves_cost_alone(self):
        self.assertEqual(self.add(self.real, 2).status_code, 201)
        self.real.refresh_from_db()
        self.assertEqual((self.real.cost, self.real.cost_estimated), (40000, False))

    def test_new_product_with_and_without_cost(self):
        body = {"category": "accessories", "brand": "Logi", "model_name": "M100", "colour": "Black", "stock_point": self.kb.id,
                "quantity": 1, "sell_price": 1000, "mrp": 1200, "specs": {"accessory_type": "Mouse", "warranty": "6 months"}}
        client = client_for(self.kb_admin)
        self.assertEqual(client.post(ADD, {**body, "cost": 650}, format="json").status_code, 201)
        bought = Variant.objects.get(product__model_name="M100")
        self.assertEqual((bought.cost, bought.cost_estimated), (650, False))
        self.assertEqual(client.post(ADD, {**body, "model_name": "M200"}, format="json").status_code, 201)
        guessed = Variant.objects.get(product__model_name="M200")
        self.assertEqual((guessed.cost, guessed.cost_estimated), (780, True))


class LockedCostTests(CostBase):
    def test_invoice_line_keeps_cost_at_sale(self):
        invoice = self.sell([{"variant": self.real, "qty": 2, "price": 50000}])
        line = invoice.items.get()
        self.assertEqual((line.unit_cost, line.cost_estimated, line.item_kind), (40000, False, InvoiceItem.PRODUCT))
        # correcting the cost later changes future sales only
        client_for(self.owner).post(f"/api/costs/variant/{self.real.id}/", {"cost": 45000}, format="json")
        line.refresh_from_db()
        self.assertEqual(line.unit_cost, 40000)
        self.assertEqual(self.quality()["cogs"], 80000)

    def test_reliability_complete_estimated_incomplete(self):
        self.sell([{"variant": self.real, "qty": 1, "price": 50000}])
        st = self.quality()
        self.assertEqual((st["data_quality"]["reliability"], st["cogs"]), ("complete", 40000))

        self.sell([{"variant": self.guess, "qty": 1, "price": 70000}])
        q = self.quality()["data_quality"]
        self.assertEqual((q["reliability"], q["estimated_cost_lines"], q["estimated_cost"], q["estimated_value"]),
                         ("estimated", 1, 54600, 70000))

        part = Part.objects.create(slug="kb-fan", name="CPU fan")  # no cost entered
        self.sell([{"description": "CPU fan", "qty": 1, "price": 1500, "item_kind": "part", "unit_cost": part.cost or None}],
                  source=Invoice.ONSITE)
        q = self.quality()["data_quality"]
        self.assertEqual((q["reliability"], q["missing_cost_lines"], q["missing_cost_value"], q["cogs_complete"]),
                         ("incomplete", 1, 1500, False))

    def test_repair_parts_cost_counts_and_labour_does_not(self):
        self.sell([
            {"description": "Screen panel", "qty": 1, "price": 6000, "item_kind": "part", "unit_cost": 3500},
            {"description": "Labour", "qty": 1, "price": 1000, "item_kind": "service"},
        ], source=Invoice.REPAIR)
        st = self.quality()
        rows = {r["source"]: r for r in st["by_source"]}
        self.assertEqual((rows["repair"]["revenue"], rows["repair"]["cogs"], rows["repair"]["gross_profit"]), (7000, 3500, 3500))
        self.assertEqual((st["cogs"], st["data_quality"]["service_revenue"], st["data_quality"]["reliability"]), (3500, 1000, "complete"))


class CostReviewTests(CostBase):
    def test_review_lists_guessed_and_missing(self):
        Part.objects.create(slug="kb-fan", name="CPU fan")
        Part.objects.create(slug="kb-key", name="Keyboard", cost=900)
        data = client_for(self.kb_admin).get(REVIEW).json()
        self.assertEqual([v["code"] for v in data["variants"]], ["VC-SKU-0002"])
        self.assertEqual([p["code"] for p in data["parts"]], ["kb-fan"])
        self.assertEqual(data["summary"], {"variants_total": 2, "variants_to_fix": 1, "parts_to_fix": 1})

    def test_store_account_sees_only_its_own_stock_and_sales(self):
        self.sell([{"variant": self.guess, "qty": 1, "price": 70000}], store=self.np)
        Stock.objects.create(variant=self.guess, stock_point=self.np, quantity=5)
        mine = client_for(self.kb_admin).get(REVIEW).json()["variants"][0]
        self.assertEqual((mine["in_stock"], mine["sold_90d"]), (2, 0))
        everyone = client_for(self.owner).get(REVIEW).json()["variants"][0]
        self.assertEqual((everyone["in_stock"], everyone["sold_90d"]), (7, 1))  # 2 at Karol Bagh + 5 at Nehru Place

    def test_store_admin_can_fix_own_product_but_not_shared_one(self):
        client = client_for(self.kb_admin)
        self.assertEqual(client.post(f"/api/costs/variant/{self.guess.id}/", {"cost": 61000}, format="json").status_code, 200)
        self.guess.refresh_from_db()
        self.assertEqual((self.guess.cost, self.guess.cost_estimated), (61000, False))
        # also on the shelf at Nehru Place -> Owner only
        self.assertEqual(client.post(f"/api/costs/variant/{self.real.id}/", {"cost": 1}, format="json").status_code, 403)
        self.assertEqual(client_for(self.owner).post(f"/api/costs/variant/{self.real.id}/", {"cost": 41000}, format="json").status_code, 200)

    def test_bad_cost_refused(self):
        client = client_for(self.owner)
        for bad in (0, -5, "abc", None):
            self.assertEqual(client.post(f"/api/costs/variant/{self.guess.id}/", {"cost": bad}, format="json").status_code, 400, bad)

    def test_part_cost(self):
        part = Part.objects.create(slug="kb-fan", name="CPU fan")
        PartStock.objects.create(part=part, stock_point=self.kb, quantity=4)
        self.assertEqual(client_for(self.kb_admin).post(f"/api/costs/part/{part.id}/", {"cost": "₹ 1,200"}, format="json").status_code, 200)
        part.refresh_from_db()
        self.assertEqual(part.cost, 1200)

    def test_bulk_is_all_or_nothing(self):
        part = Part.objects.create(slug="kb-fan", name="CPU fan")
        client = client_for(self.kb_admin)
        bad = client.post("/api/costs/bulk/", {"rows": [
            {"code": "vc-sku-0002", "cost": 60000}, {"code": "NOPE", "cost": 5}, {"code": "VC-SKU-0001", "cost": 41000},
        ]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(len(bad.json()["problems"]), 2)  # unknown code + shared product
        self.guess.refresh_from_db()
        self.assertTrue(self.guess.cost_estimated)
        good = client.post("/api/costs/bulk/", {"rows": [{"code": "vc-sku-0002", "cost": 60000}, {"code": "KB-FAN", "cost": 800}]}, format="json")
        self.assertEqual(good.json(), {"saved": 2, "problems": []})
        self.guess.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual((self.guess.cost, self.guess.cost_estimated, part.cost), (60000, False, 800))

    def test_needs_inventory_edit(self):
        viewer = make_user("viewer", ["inventory.view"], stock_point=self.kb)
        self.assertEqual(client_for(viewer).get(REVIEW).status_code, 403)


class RepairCostPrivacyTests(TestCase):
    def test_our_cost_is_never_on_the_customer_serializer(self):
        self.assertNotIn("unit_cost", RepairEstimateLineSerializer.Meta.fields)
        self.assertIn("unit_cost", StaffRepairEstimateLineSerializer.Meta.fields)
