"""
Suppliers and what was bought from them (catalog.Purchase).

  * Add stock with a supplier -> one Purchase, and the new units' serial
    numbers point to it.
  * Stock already held (or already sold) can be tagged afterwards: pick the
    units by serial number -- or, for a product without serial numbers, just
    the quantity -- and the supplier bill they came on.
  * A supplier's history: every purchase, how many of those units have been
    sold and what they earned (sale price on the bill line - price paid).
  * The comparison: for the same product (same variant), which supplier's
    units earn more per unit.

Profit per unit is only known for units with a serial number (we know which
sale each one went out on). For a product without serial numbers the
comparison shows the expected margin instead: today's selling price - the
supplier's price.
"""
from collections import defaultdict
from datetime import date

from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from parties.models import Party

from .models import Purchase, StockSerial, SupplierPayment, Variant


def supplier_from(value, field="supplier"):
    """The Supplier party with this id, or a validation error."""
    try:
        party = Party.objects.get(pk=int(value))
    except (TypeError, ValueError, Party.DoesNotExist):
        raise serializers.ValidationError({field: ["Choose a supplier."]})
    if party.type != Party.SUPPLIER:
        raise serializers.ValidationError({field: [f"{party.name} isn't a supplier. Set their type to Supplier in Parties first."]})
    return party


def record(*, supplier, variant, stock_point, qty, unit_cost, user, bill_no="", purchased_on=None, serials=(), tagged=False,
           note="", already_paid=False):
    purchase = Purchase.objects.create(
        supplier=supplier, variant=variant, stock_point=stock_point, qty=qty, unit_cost=unit_cost,
        bill_no=(bill_no or "").strip()[:60], purchased_on=purchased_on or date.today(), tagged=tagged,
        note=(note or "").strip()[:200], recorded_by=user, already_paid=already_paid,
    )
    if serials:
        StockSerial.objects.filter(serial_number__in=list(serials), variant=variant).update(purchase=purchase)
    return purchase


class TagSerializer(serializers.Serializer):
    """Set the supplier on stock that's already held or sold."""
    supplier = serializers.IntegerField()
    variant = serializers.IntegerField()
    unit_cost = serializers.IntegerField(min_value=1, max_value=100_000_000)
    bill_no = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    purchased_on = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    # the units, by serial number; or for a product without serials, a quantity
    serials = serializers.ListField(child=serializers.CharField(max_length=80), required=False, default=list, max_length=500)
    qty = serializers.IntegerField(min_value=1, max_value=10_000, required=False, allow_null=True)
    # old stock was usually paid for long ago: then it adds nothing to what they're owed
    already_paid = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        attrs["supplier"] = supplier_from(attrs["supplier"])
        try:
            attrs["variant"] = Variant.objects.select_related("product").get(pk=attrs["variant"])
        except Variant.DoesNotExist:
            raise serializers.ValidationError({"variant": ["Choose the product."]})
        if attrs.get("purchased_on") and attrs["purchased_on"] > date.today():
            raise serializers.ValidationError({"purchased_on": ["The purchase date can't be in the future."]})
        wanted = list(dict.fromkeys(s.strip() for s in attrs["serials"] if s.strip()))
        if wanted:
            units = list(StockSerial.objects.filter(variant=attrs["variant"], serial_number__in=wanted).select_related("purchase__supplier"))
            found = {u.serial_number for u in units}
            missing = [s for s in wanted if s not in found]
            if missing:
                raise serializers.ValidationError({"serials": [f"Not units of this product: {', '.join(missing[:5])}"]})
            done = [u for u in units if u.purchase_id]
            if done:
                raise serializers.ValidationError({"serials": [
                    f"{done[0].serial_number} is already on a bill from {done[0].purchase.supplier.name}."
                    + (f" (and {len(done) - 1} more)" if len(done) > 1 else "")]})
            attrs["units"] = units
            attrs["qty"] = len(units)
        elif not attrs.get("qty"):
            raise serializers.ValidationError({"serials": ["Pick the units (serial numbers), or enter how many."]})
        else:
            attrs["units"] = []
        return attrs


@transaction.atomic
def tag(data, user):
    units = data["units"]
    stock_point = units[0].stock_point if units else None
    if stock_point is None:
        stock = data["variant"].stock.order_by("-quantity").first()
        stock_point = stock.stock_point if stock else None
    if stock_point is None:
        raise serializers.ValidationError({"variant": ["This product isn't stocked at any shop."]})
    return record(
        supplier=data["supplier"], variant=data["variant"], stock_point=stock_point, qty=data["qty"],
        unit_cost=data["unit_cost"], user=user, bill_no=data["bill_no"], purchased_on=data.get("purchased_on"),
        serials=[u.serial_number for u in units], tagged=True, note=data["note"], already_paid=data["already_paid"],
    )


# --------------------------------------------------------------------------
# Paying suppliers
# --------------------------------------------------------------------------

def balance(supplier):
    """(bills owed, paid, still owed) in rupees. Negative still-owed = an advance with them."""
    bills = sum(p.amount for p in supplier.purchases.all() if not p.already_paid)
    paid = sum(p.amount for p in supplier.supplier_payments.all())
    return bills, paid, bills - paid


class PaySerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1, max_value=100_000_000)
    paid_on = serializers.DateField()
    method = serializers.CharField(max_length=40)
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    purchase = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        from sales.models import PAYMENT_METHODS

        errors = {}
        if attrs["method"] not in PAYMENT_METHODS:
            errors["method"] = [f"Choose one of: {', '.join(PAYMENT_METHODS)}."]
        if attrs["paid_on"] > date.today():
            errors["paid_on"] = ["The payment date can't be in the future."]
        supplier = self.context["supplier"]
        if attrs.get("purchase"):
            attrs["purchase"] = supplier.purchases.filter(pk=attrs["purchase"]).first()
            if attrs["purchase"] is None:
                errors["purchase"] = ["That bill isn't from this supplier."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


def _post_payment(payment):
    """The money going out: cash book for Cash, the business bank account otherwise."""
    from accounting.models import BankEntry, CashEntry
    from accounting.posting import default_bank_account

    bill = f" (bill {payment.purchase.bill_no})" if payment.purchase_id and payment.purchase.bill_no else ""
    particulars = f"Paid to supplier {payment.supplier.name}{bill}"
    if payment.method == "Cash":
        return CashEntry.objects.create(date=payment.paid_on, particulars=particulars[:160], type=CashEntry.OUT,
                                        amount=payment.amount, by=payment.by, supplier_payment=payment)
    return BankEntry.objects.create(account=default_bank_account(), date=payment.paid_on, type=BankEntry.OUT,
                                    amount=payment.amount, particulars=f"{particulars} via {payment.method}"[:160],
                                    reference=payment.reference[:80], supplier_payment=payment)


@transaction.atomic
def pay(supplier, data, user):
    payment = SupplierPayment.objects.create(
        supplier=supplier, amount=data["amount"], paid_on=data["paid_on"], method=data["method"],
        reference=(data.get("reference") or "").strip()[:80], note=(data.get("note") or "").strip()[:200],
        purchase=data.get("purchase"), by=user,
    )
    _post_payment(payment)
    return payment


def _sold(units):
    """Units out on a paid (or partly refunded) sale -- [(unit, sale price)]."""
    from sales.models import Invoice

    return [(u, u.invoice_item.price) for u in units
            if u.status == StockSerial.SOLD and u.invoice_item_id and u.invoice_item.invoice.status in Invoice.SETTLED]


def history(supplier):
    """Every purchase from this supplier, with what its units earned."""
    purchases = (supplier.purchases.select_related("variant__product", "stock_point")
                 .prefetch_related("units__invoice_item__invoice"))
    rows = []
    for p in purchases:
        units = list(p.units.all())
        sold = _sold(units)
        revenue = sum(price for _, price in sold)
        rows.append({
            "id": p.id, "purchased_on": p.purchased_on, "bill_no": p.bill_no, "tagged": p.tagged, "note": p.note,
            "already_paid": p.already_paid,
            "product": p.variant.product.display_name, "spec": p.variant.spec, "variant": p.variant_id,
            "store": p.stock_point.name, "qty": p.qty, "unit_cost": p.unit_cost, "amount": p.amount,
            "serials": [u.serial_number for u in units],
            "in_stock": sum(1 for u in units if u.status == StockSerial.IN_STOCK),
            "sold": len(sold), "sold_for": revenue, "profit": revenue - len(sold) * p.unit_cost,
        })
    # the ledger: bills (what we owe) and payments (what we paid), oldest first, with the running balance
    events = [{"date": r["purchased_on"], "kind": "bill", "id": f"b{r['id']}",
               "text": f"{r['qty']} × {r['product']} ({r['spec']})" + (f" · bill {r['bill_no']}" if r["bill_no"] else ""),
               "bill": 0 if r["already_paid"] else r["amount"], "paid": 0, "note": "paid before it was recorded" if r["already_paid"] else ""}
              for r in rows]
    payments = list(supplier.supplier_payments.select_related("purchase", "by"))
    events += [{"date": p.paid_on, "kind": "payment", "id": f"p{p.id}",
                "text": f"Paid by {p.method}" + (f" · ref {p.reference}" if p.reference else "")
                        + (f" · for bill {p.purchase.bill_no}" if p.purchase_id and p.purchase.bill_no else ""),
                "bill": 0, "paid": p.amount, "note": p.note} for p in payments]
    events.sort(key=lambda e: (e["date"], e["kind"] == "payment", e["id"]))
    running = 0
    for e in events:
        running += e["bill"] - e["paid"]
        e["balance"] = running
    bills, paid, owed = balance(supplier)
    return {
        "supplier": {"id": supplier.id, "name": supplier.name, "phone": supplier.phone, "gstin": supplier.gstin, "city": supplier.city},
        "ledger": events,
        "owed": {"bills": bills, "paid": paid, "balance": owed},
        "purchases": rows,
        "totals": {
            "bills": len({(r["bill_no"] or f"#{r['id']}") for r in rows}), "qty": sum(r["qty"] for r in rows),
            "amount": sum(r["amount"] for r in rows), "sold": sum(r["sold"] for r in rows),
            "sold_for": sum(r["sold_for"] for r in rows), "profit": sum(r["profit"] for r in rows),
        },
    }


def comparison(store_ids=None):
    """
    For each product (variant) bought from more than one supplier -- or from
    one, so it still shows -- each supplier's: units bought, average price
    paid, units sold, average sale price, profit per unit and in total.
    `best` marks the supplier earning the most per unit on that product.
    """
    purchases = Purchase.objects.select_related("supplier", "variant__product").prefetch_related("units__invoice_item__invoice")
    if store_ids is not None:
        purchases = purchases.filter(stock_point_id__in=list(store_ids))
    grid = defaultdict(lambda: defaultdict(lambda: {"bought": 0, "paid": 0, "units": []}))
    variants = {}
    for p in purchases:
        cell = grid[p.variant_id][p.supplier_id]
        cell["bought"] += p.qty
        cell["paid"] += p.amount
        cell["name"] = p.supplier.name
        cell["units"] += [(u, p.unit_cost) for u in p.units.all()]
        variants[p.variant_id] = p.variant
    products = []
    for variant_id, suppliers in grid.items():
        v = variants[variant_id]
        rows = []
        for supplier_id, cell in suppliers.items():
            avg_cost = round(cell["paid"] / cell["bought"]) if cell["bought"] else 0
            sold = _sold([u for u, _ in cell["units"]])
            cost_of = {u.pk: c for u, c in cell["units"]}
            if sold:
                revenue = sum(price for _, price in sold)
                profit = revenue - sum(cost_of[u.pk] for u, _ in sold)
                per_unit, basis = round(profit / len(sold)), "sold"
                avg_sale = round(revenue / len(sold))
            else:
                # nothing sold yet (or no serial numbers): what it should earn at today's price
                profit, avg_sale = 0, None
                per_unit, basis = v.sell_price - avg_cost, "expected"
            rows.append({
                "supplier_id": supplier_id, "supplier": cell["name"], "bought": cell["bought"], "avg_cost": avg_cost,
                "sold": len(sold), "avg_sale": avg_sale, "profit": profit, "profit_per_unit": per_unit,
                "margin_pct": round(per_unit * 100 / (avg_sale or v.sell_price), 1) if (avg_sale or v.sell_price) else None,
                "basis": basis,
            })
        rows.sort(key=lambda r: -r["profit_per_unit"])
        if rows:
            rows[0]["best"] = len(rows) > 1
        products.append({
            "variant": variant_id, "product": v.product.display_name, "spec": v.spec, "code": v.code,
            "sell_price": v.sell_price, "suppliers": rows,
            "gap_per_unit": rows[0]["profit_per_unit"] - rows[-1]["profit_per_unit"] if len(rows) > 1 else 0,
        })
    # products with a real choice between suppliers first, biggest difference first
    products.sort(key=lambda p: (-(len(p["suppliers"]) > 1), -p["gap_per_unit"], p["product"]))
    supplier_totals = defaultdict(lambda: {"bought": 0, "paid": 0, "sold": 0, "profit": 0})
    for prod in products:
        for r in prod["suppliers"]:
            t = supplier_totals[r["supplier_id"]]
            t["supplier"] = r["supplier"]
            t["bought"] += r["bought"]
            t["paid"] += r["bought"] * r["avg_cost"]
            t["sold"] += r["sold"]
            t["profit"] += r["profit"]
    return {
        "products": products,
        "suppliers": sorted(({"supplier_id": k, **v} for k, v in supplier_totals.items()), key=lambda r: -r["profit"]),
        "untagged_units": StockSerial.objects.filter(purchase__isnull=True).filter(
            Q(stock_point_id__in=list(store_ids)) if store_ids is not None else Q()).count(),
    }
