"""Suppliers: stock added with a supplier, tagging old stock, history and the profit comparison."""
from datetime import date

from django.test import TestCase

from catalog.models import Product, Purchase, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user
from parties.models import Party
from sales.models import Invoice
from sales.services import create_invoice


class SupplierTests(TestCase):
    def setUp(self):
        self.shop = StockPoint.objects.create(slug="sup-shop", name="Supplier Shop", kind=StockPoint.SHOP)
        self.owner = make_user("sup-owner", superuser=True)
        self.client_ = client_for(self.owner)
        self.alpha = Party.objects.create(name="Alpha Traders", type=Party.SUPPLIER, phone="9811111111", joined=date(2026, 1, 1))
        self.beta = Party.objects.create(name="Beta Imports", type=Party.SUPPLIER, phone="9822222222", joined=date(2026, 1, 1))
        self.buyer = Party.objects.create(name="Walk-in", type=Party.RETAIL, phone="9833333333", joined=date(2026, 1, 1))
        product = Product.objects.create(model_name="IdeaPad 5", brand="Lenovo", product_code="P-SUP", serial_tracking=True)
        self.variant = Variant.objects.create(product=product, code="V-SUP", spec="16GB", mrp=60000, sell_price=55000, cost=45000)
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=0)

    def add_stock(self, supplier, qty, cost, bill="B-1"):
        response = self.client_.post("/api/inventory/add-stock/", {
            "entry": "existing", "stock_point": self.shop.id, "product": self.variant.product_id, "variant": self.variant.id,
            "quantity": qty, "cost": cost, "supplier": supplier.id if supplier else None, "bill_no": bill,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["serials"]

    def sell(self, serial, price):
        unit = StockSerial.objects.get(serial_number=serial)
        invoice = create_invoice(lines=[{"variant": self.variant, "qty": 1, "price": price}], party=self.buyer,
                                 stock_point=self.shop, date=date.today(), status=Invoice.PAID, pay_method="Cash")
        unit.status, unit.invoice_item = StockSerial.SOLD, invoice.items.get()
        unit.save()

    def test_stock_added_with_a_supplier_records_the_bill_and_its_units(self):
        serials = self.add_stock(self.alpha, 2, 44000, bill="AL-77")
        purchase = Purchase.objects.get()
        self.assertEqual((purchase.supplier, purchase.qty, purchase.unit_cost, purchase.bill_no), (self.alpha, 2, 44000, "AL-77"))
        self.assertEqual(set(purchase.units.values_list("serial_number", flat=True)), set(serials))

    def test_only_a_supplier_can_be_chosen(self):
        response = self.client_.post("/api/inventory/add-stock/", {
            "entry": "existing", "stock_point": self.shop.id, "product": self.variant.product_id, "variant": self.variant.id,
            "quantity": 1, "supplier": self.buyer.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("isn't a supplier", str(response.json()))

    def test_history_shows_what_each_bill_earned(self):
        serials = self.add_stock(self.alpha, 2, 44000)
        self.sell(serials[0], 54000)
        body = self.client_.get(f"/api/purchases/supplier/{self.alpha.id}/").json()
        row = body["purchases"][0]
        self.assertEqual((row["qty"], row["sold"], row["in_stock"], row["sold_for"], row["profit"]), (2, 1, 1, 54000, 10000))
        self.assertEqual(body["totals"]["amount"], 88000)

    def test_old_stock_can_be_tagged_and_not_twice(self):
        serials = self.add_stock(None, 3, 45000)  # no supplier at the time
        self.sell(serials[0], 53000)
        untagged = self.client_.get(f"/api/purchases/untagged/?variant={self.variant.id}").json()
        self.assertEqual(len(untagged), 3)
        response = self.client_.post("/api/purchases/tag/", {"supplier": self.beta.id, "variant": self.variant.id,
                                                             "unit_cost": 46000, "serials": serials[:2], "bill_no": "OLD-1"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(Purchase.objects.get().tagged)
        again = self.client_.post("/api/purchases/tag/", {"supplier": self.alpha.id, "variant": self.variant.id,
                                                          "unit_cost": 40000, "serials": serials[:1]}, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertIn("Beta Imports", str(again.json()))

    def test_comparison_shows_which_supplier_earns_more_per_unit(self):
        a = self.add_stock(self.alpha, 2, 44000)
        b = self.add_stock(self.beta, 2, 47000, bill="BE-1")
        self.sell(a[0], 55000)   # +11000
        self.sell(b[0], 55000)   # +8000
        body = self.client_.get("/api/reports/supplier-comparison/").json()
        product = body["products"][0]
        best, other = product["suppliers"]
        self.assertEqual((best["supplier"], best["profit_per_unit"], best.get("best")), ("Alpha Traders", 11000, True))
        self.assertEqual((other["supplier"], other["profit_per_unit"]), ("Beta Imports", 8000))
        self.assertEqual(product["gap_per_unit"], 3000)
        self.assertEqual(body["suppliers"][0]["supplier"], "Alpha Traders")

    def test_comparison_is_profit_and_loss_only(self):
        staff = client_for(make_user("sup-staff", ["inventory.edit"], stock_point=self.shop))
        self.assertEqual(staff.get("/api/reports/supplier-comparison/").status_code, 403)
        self.assertEqual(staff.get(f"/api/purchases/supplier/{self.alpha.id}/").status_code, 200)


class NewSupplierTests(TestCase):
    """Add stock -> "+ New supplier": a Supplier party needs no email; a customer still does."""

    def setUp(self):
        self.client_ = client_for(make_user("ns-owner", superuser=True))

    def test_supplier_without_email_customer_with(self):
        body = {"name": "Delta Distributors", "type": "Supplier", "phone": "9876501111", "city": "Delhi",
                "customer_classification": "business", "joined": "2026-11-09"}
        self.assertEqual(self.client_.post("/api/parties/", body, format="json").status_code, 201)
        customer = {**body, "name": "Walk-in", "type": "Retail", "phone": "9876502222"}
        response = self.client_.post("/api/parties/", customer, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())


class SupplierPaymentTests(TestCase):
    """Money paid to suppliers: goes out of the cash / bank book and lowers what they're owed."""

    def setUp(self):
        from accounting.models import BankEntry, CashEntry

        self.Cash, self.Bank = CashEntry, BankEntry
        self.shop = StockPoint.objects.create(slug="pay-shop", name="Pay Shop", kind=StockPoint.SHOP)
        self.client_ = client_for(make_user("pay-owner", superuser=True))
        self.supplier = Party.objects.create(name="Gamma Supplies", type=Party.SUPPLIER, phone="9844444444", joined=date(2026, 1, 1))
        product = Product.objects.create(model_name="Vostro", brand="Dell", product_code="P-PAY", serial_tracking=True)
        self.variant = Variant.objects.create(product=product, code="V-PAY", spec="8GB", mrp=50000, sell_price=45000, cost=38000)
        Stock.objects.create(variant=self.variant, stock_point=self.shop, quantity=0)

    def add(self, qty, cost, **extra):
        response = self.client_.post("/api/inventory/add-stock/", {
            "entry": "existing", "stock_point": self.shop.id, "product": self.variant.product_id, "variant": self.variant.id,
            "quantity": qty, "cost": cost, "supplier": self.supplier.id, **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def pay(self, amount, method="Cash", **extra):
        return self.client_.post(f"/api/purchases/supplier/{self.supplier.id}/pay/",
                                 {"amount": amount, "paid_on": date.today().isoformat(), "method": method, **extra}, format="json")

    def ledger(self):
        return self.client_.get(f"/api/purchases/supplier/{self.supplier.id}/").json()

    def test_bill_then_part_payments_balance_out(self):
        self.add(2, 40000)  # owed 80,000
        self.assertEqual(self.ledger()["owed"]["balance"], 80000)
        self.assertEqual(self.pay(30000).status_code, 201)
        self.assertEqual(self.pay(50000, method="UPI", reference="UTR123").status_code, 201)
        body = self.ledger()
        self.assertEqual(body["owed"], {"bills": 80000, "paid": 80000, "balance": 0})
        self.assertEqual([e["balance"] for e in body["ledger"]], [80000, 50000, 0])
        cash = self.Cash.objects.get(supplier_payment__isnull=False)
        self.assertEqual((cash.type, cash.amount), ("out", 30000))
        bank = self.Bank.objects.get(supplier_payment__isnull=False)
        self.assertEqual((bank.type, bank.amount, bank.reference), ("out", 50000, "UTR123"))
        party = self.client_.get(f"/api/parties/{self.supplier.id}/").json()
        self.assertEqual(party["supplier_owed"], 0)

    def test_paid_in_full_on_arrival(self):
        self.add(1, 39000, paid_method="Cash")
        self.assertEqual(self.ledger()["owed"]["balance"], 0)
        self.assertEqual(self.Cash.objects.get(supplier_payment__isnull=False).amount, 39000)

    def test_old_stock_tagged_as_already_paid_adds_nothing_owed(self):
        response = self.client_.post("/api/purchases/tag/", {"supplier": self.supplier.id, "variant": self.variant.id,
                                                             "unit_cost": 37000, "qty": 2}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.ledger()["owed"]["balance"], 0)

    def test_overpaying_leaves_an_advance_and_bad_input_is_refused(self):
        self.assertEqual(self.pay(5000).status_code, 201)
        self.assertEqual(self.ledger()["owed"]["balance"], -5000)
        self.assertEqual(self.pay(100, method="Barter").status_code, 400)
        self.assertEqual(self.pay(0).status_code, 400)

    def test_only_those_who_pay_expenses_can_pay_suppliers(self):
        staff = client_for(make_user("pay-staff", ["inventory.edit"], stock_point=self.shop))
        response = staff.post(f"/api/purchases/supplier/{self.supplier.id}/pay/",
                              {"amount": 100, "paid_on": date.today().isoformat(), "method": "Cash"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(staff.get(f"/api/purchases/supplier/{self.supplier.id}/").json()["can_pay"])
