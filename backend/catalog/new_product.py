"""
Inventory -> Add stock: New product and Existing product.

Reuses the existing catalogue (Product -> Variant -> Stock per stock point)
and the existing endpoint (catalog.views.AddStockView, which handles the
permission, the store scope and the inactive-store rule before calling in
here, inside one transaction).

  Product ID   Product.product_code -- one per product, generated once by
               utils.next_code (VC-LAP-#### / VC-ACC-####); never per unit.
  Variant SKU  Variant.code (VC-SKU-####) -- one per colour / specification.
  Serial No.   StockSerial.serial_number -- one per physical unit, generated
               here (never typed, never sent by the browser).
  HSN code     Product.hsn -- one per product, shared by all its units.

Colour lives on the Variant, typed in by staff. A product received in a new
colour (or a new specification) is a new Variant of the same Product, so
units already in stock keep the colour they were received with:
  same specification + same colour (case-insensitive) -> that Variant
  anything else                                        -> a new Variant
The variant's `spec` -- what invoices, labels and the stock list show -- is
built from the category's specifications (spec_summary).
"""
import re
import secrets

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Upper
from rest_framework import serializers

from rentals.models import RentalAsset

from .models import Product, SerialEvent, Stock, StockSerial, Variant
from .utils import next_code

MAX_QUANTITY = 1000
MAX_COLOUR_LENGTH = 40
# HSN entered on this form: exactly ten digits (Product.hsn holds up to 12;
# codes already saved in other lengths are kept as they are)
HSN_RE = re.compile(r"^\d{10}$")
HSN_ERROR = "Enter the HSN code as exactly 10 digits, or leave it empty."
# the existing cost estimate when no purchase cost is entered (catalog.views._resolve_variant)
ESTIMATED_COST_SHARE = 0.78

# Serial numbers: 2 letters from the product's name + 5 random digits, e.g. LA58321
SERIAL_RE = re.compile(r"^[A-Z]{2}\d{5}$")
SERIAL_SPACE = 100_000          # 00000-99999 per two-letter prefix
SERIAL_ATTEMPTS = 8             # tries at inserting a batch before giving up
NAME_TOO_SHORT = "The product name needs at least two letters (A–Z) to make its serial numbers."
MANUAL_SERIALS = "Serial numbers are generated automatically for every unit -- don't send them."

# Categories and the details each asks for live in the database
# (catalog.ProductCategory) so an Admin can edit them at run time; brand,
# product name, colour and HSN are common to every category.
CONDITIONS = ["New", "Refurbished", "Used"]


def category_for(key, active_only=True):
    from .models import ProductCategory

    qs = ProductCategory.objects.filter(key=key)
    return (qs.filter(is_active=True) if active_only else qs).first()


def spec_summary(category, specs):
    """The variant's spec line from the category's summary fields, in order
    (the first three fields if none is marked)."""
    fields = category.fields if category else []
    keys = [f["key"] for f in fields if f.get("summary")] or [f["key"] for f in fields[:3]]
    parts = [specs[k] for k in keys if specs.get(k)]
    return " / ".join(parts)[:80] or "Standard"


def clean_colour(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def clean_hsn(value, errors):
    hsn = re.sub(r"\s+", "", value or "")
    if hsn and not HSN_RE.match(hsn):
        errors["hsn"] = [HSN_ERROR]
    return hsn


def refuse_manual_serials(initial, errors):
    if initial.get("serials"):
        errors["serials"] = [MANUAL_SERIALS]


# --------------------------------------------------------------------------
# Serial numbers
# --------------------------------------------------------------------------

def serial_prefix(name):
    """The first two letters (A-Z) of the product's name, upper-cased --
    "Dell Latitude" -> "DE", "Laptop" -> "LA". None with fewer than two."""
    letters = re.findall(r"[A-Za-z]", name or "")
    return "".join(letters[:2]).upper() if len(letters) >= 2 else None


def _taken(candidates):
    """Which of these serial numbers already exist -- as a unit in stock or
    as a rental device -- compared case-insensitively."""
    if not candidates:
        return set()
    upper = [c.upper() for c in candidates]
    found = set(StockSerial.objects.annotate(u=Upper("serial_number")).filter(u__in=upper).values_list("u", flat=True))
    found |= set(RentalAsset.objects.annotate(u=Upper("serial_number")).filter(u__in=upper).values_list("u", flat=True))
    return found


def _in_use(prefix):
    return StockSerial.objects.filter(serial_number__regex=rf"^{prefix}[0-9]{{5}}$").count()


def generate_serials(prefix, variant, stock_point, user, count):
    """
    Record `count` new units with their own serial numbers: prefix + five
    random digits, unique across the database. Candidates already used are
    redrawn; the insert runs in a savepoint, so if a concurrent stock
    addition took one of them first (the unique index refuses it) the batch
    is drawn again rather than failing or duplicating. Returns the serials.
    """
    if _in_use(prefix) + count > SERIAL_SPACE:
        raise serializers.ValidationError({"quantity": [
            f"There aren't {count} unused serial numbers left starting with {prefix}. Contact support."
        ]})
    for _ in range(SERIAL_ATTEMPTS):
        chosen = set()
        for _ in range(200):
            if len(chosen) == count:
                break
            need = count - len(chosen)
            draw = {f"{prefix}{secrets.randbelow(SERIAL_SPACE):05d}" for _ in range(need * 2 + 4)} - chosen
            chosen |= set(sorted(draw - _taken(draw))[:need])
        if len(chosen) < count:
            continue
        try:
            with transaction.atomic():
                StockSerial.objects.bulk_create([
                    StockSerial(variant=variant, stock_point=stock_point, serial_number=s, received_by=user) for s in chosen
                ])
                SerialEvent.objects.bulk_create([
                    SerialEvent(serial=s, event=SerialEvent.RECEIVED, text=f"Received into stock at {stock_point.name}",
                                stock_point=stock_point, actor=user)
                    for s in StockSerial.objects.filter(serial_number__in=chosen)
                ])
            return sorted(chosen)
        except IntegrityError:
            continue  # taken by a stock addition running at the same moment -- draw again
    raise serializers.ValidationError({"detail": ["Serial numbers couldn't be allocated just now. Please try again."]})


def _check_prices(sell, mrp, errors):
    if sell is not None and mrp is not None and mrp < sell:
        errors["mrp"] = ["MRP can't be lower than the selling price."]


# --------------------------------------------------------------------------
# New product
# --------------------------------------------------------------------------

class NewProductSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=20)
    brand = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    model_name = serializers.CharField(max_length=80)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    condition = serializers.ChoiceField(choices=CONDITIONS, required=False, default="New")
    colour = serializers.CharField(max_length=MAX_COLOUR_LENGTH, required=False, allow_blank=True, default="")
    # one HSN for the product -- every variant and unit of it shares it
    hsn = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    specs = serializers.DictField(child=serializers.CharField(max_length=120, allow_blank=True), required=False, default=dict)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)
    sell_price = serializers.IntegerField(min_value=1, max_value=100_000_000)
    # purchase price per unit (from the supplier bill); blank = estimated for now
    cost = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False, allow_null=True)
    mrp = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False, allow_null=True)
    location = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    # optional: who it was bought from (a Supplier party) and their bill number
    supplier = serializers.IntegerField(required=False, allow_null=True)
    bill_no = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    # paid for in full when it arrived (Cash / UPI / ...); blank = bought on credit, owed to the supplier
    paid_method = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs.get("supplier"):
            from .purchases import supplier_from

            attrs["supplier"] = supplier_from(attrs["supplier"])
        category = category_for(attrs["category"])
        if category is None:
            raise serializers.ValidationError({"category": ["Choose a product category."]})
        attrs["category_obj"] = category
        errors = {}
        refuse_manual_serials(self.initial_data, errors)
        attrs["brand"] = attrs["brand"].strip()
        attrs["model_name"] = attrs["model_name"].strip()
        attrs["colour"] = clean_colour(attrs["colour"])
        attrs["hsn"] = clean_hsn(attrs["hsn"], errors)
        if not attrs["model_name"]:
            errors["model_name"] = ["Enter the model / product name."]
        if not attrs["brand"] and category.brand_required:
            errors["brand"] = ["Enter the brand."]
        name = f"{attrs['brand']} {attrs['model_name']}".strip()
        if attrs["model_name"] and not serial_prefix(name):
            errors.setdefault("model_name", []).append(NAME_TOO_SHORT)

        # keep only this category's details (as the Admin set them up); refuse unknown keys
        allowed = {f["key"]: f for f in category.fields}
        raw = attrs.get("specs") or {}
        unknown = sorted(set(raw) - set(allowed))
        if unknown:
            errors["specs"] = [f"Not a {category.name} detail: {', '.join(unknown)}."]
        specs = {}
        for key, field in allowed.items():
            value = (raw.get(key) or "").strip()
            if field.get("required") and not value:
                errors[f"specs.{key}"] = [f"Enter the {field['label'].lower()}."]
            options = field.get("options") if field.get("type") == "choice" else None
            if value and options and value not in options:
                errors[f"specs.{key}"] = [f"Choose one of: {', '.join(options)}."]
            if value:
                specs[key] = value
        attrs["specs"] = specs
        _check_prices(attrs["sell_price"], attrs.get("mrp"), errors)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


def find_duplicate(data, spec):
    """The same brand + name + category + specification is already in the
    catalogue -- in any colour. A new colour of it is a new variant of that
    product (Existing product), not a second product."""
    return (Variant.objects.select_related("product")
            .filter(product__brand__iexact=data["brand"] or "—", product__model_name__iexact=data["model_name"],
                    product__category=data["category"], spec__iexact=spec).first())


def create(data, user, stock_point):
    """One Product (one Product ID), its first Variant, the store's stock and
    one serial number per unit -- all inside AddStockView's transaction.
    Returns (product, variant, stock, serials)."""
    category = data["category_obj"]
    spec = spec_summary(category, data["specs"])
    duplicate = find_duplicate(data, spec)
    if duplicate:
        raise serializers.ValidationError({"model_name": [
            f"{duplicate.product.display_name} ({spec}) is already in the catalogue as {duplicate.product.product_code}. "
            "Use Existing product to add stock or a new colour."
        ]})
    specs = data["specs"]
    product = Product.objects.create(
        category=data["category"], brand=data["brand"] or "—", model_name=data["model_name"],
        processor=specs.get("processor", "")[:40], condition=data["condition"], description=data["description"].strip(),
        hsn=data["hsn"], specs=specs, serial_tracking=True,
        product_code=next_code(category.code_prefix or "VC-ACC", Product, "product_code"),
    )
    sell = data["sell_price"]
    bought = data.get("cost")
    variant = Variant.objects.create(
        product=product, spec=spec, colour=data["colour"], sell_price=sell, mrp=data.get("mrp") or sell,
        # the purchase price when entered; otherwise the estimate, flagged as such
        cost=bought or round(sell * ESTIMATED_COST_SHARE), cost_estimated=not bought,
        code=next_code("VC-SKU", Variant, "code"),
    )
    stock = Stock.objects.create(variant=variant, stock_point=stock_point, quantity=data["quantity"],
                                 location=data["location"].strip())
    serials = generate_serials(serial_prefix(product.display_name), variant, stock_point, user, data["quantity"])
    return product, variant, stock, serials


# --------------------------------------------------------------------------
# Existing product
# --------------------------------------------------------------------------

class ExistingStockSerializer(serializers.Serializer):
    """Receive stock of a catalogue product: into one of its variants
    (`variant`), or into a new colour / specification of it (`new_variant`)."""
    product = serializers.IntegerField()
    variant = serializers.IntegerField(required=False, allow_null=True)
    new_variant = serializers.BooleanField(required=False, default=False)
    colour = serializers.CharField(max_length=MAX_COLOUR_LENGTH, required=False, allow_blank=True, default="")
    spec = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    # blank keeps the product's saved HSN; a valid value replaces it
    hsn = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)
    sell_price = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False, allow_null=True)
    cost = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False, allow_null=True)
    mrp = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False, allow_null=True)
    location = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    # optional: who it was bought from (a Supplier party) and their bill number
    supplier = serializers.IntegerField(required=False, allow_null=True)
    bill_no = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    # paid for in full when it arrived (Cash / UPI / ...); blank = bought on credit, owed to the supplier
    paid_method = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs.get("supplier"):
            from .purchases import supplier_from

            attrs["supplier"] = supplier_from(attrs["supplier"])
        errors = {}
        refuse_manual_serials(self.initial_data, errors)
        attrs["colour"] = clean_colour(attrs["colour"])
        attrs["spec"] = attrs["spec"].strip()
        attrs["hsn"] = clean_hsn(attrs["hsn"], errors)
        product = Product.objects.filter(pk=attrs["product"]).prefetch_related("variants").first()
        if product is None:
            raise serializers.ValidationError({"product": ["That product isn't in the catalogue."]})
        attrs["product"] = product
        if not serial_prefix(product.display_name):
            errors["product"] = [NAME_TOO_SHORT]
        variants = list(product.variants.all())

        if attrs["new_variant"]:
            spec = attrs["spec"] or "Standard"
            same = next((v for v in variants if v.spec.lower() == spec.lower() and v.colour.lower() == attrs["colour"].lower()), None)
            if same:
                # it already exists -- never a second identical variant
                errors["variant"] = [f"{same.code} is already {spec}{f' in {same.colour}' if same.colour else ''}. Select that variant instead."]
            if not attrs.get("sell_price"):
                errors["sell_price"] = ["Enter the selling price for the new variant."]
            attrs["spec"] = spec
            attrs["variant"] = None
            _check_prices(attrs.get("sell_price"), attrs.get("mrp"), errors)
        else:
            variant = next((v for v in variants if v.pk == attrs.get("variant")), None)
            if variant is None:
                errors["variant"] = ["Choose the variant this stock belongs to, or add a new colour / specification."]
            else:
                attrs["variant"] = variant
                typed = attrs["colour"].lower()
                if typed and typed != variant.colour.lower():
                    # never relabel units already in stock
                    have = f"is {variant.colour}" if variant.colour else "has no colour recorded"
                    errors["colour"] = [f"{variant.code} {have}. To receive {attrs['colour']} units, add them as a new colour."]
            sell = attrs.get("sell_price") or (variant.sell_price if variant else None)
            mrp = attrs.get("mrp") or (variant.mrp if variant else None)
            _check_prices(sell, mrp, errors)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


def add_existing(data, user, stock_point):
    """Add the units to the chosen (or new) variant at this store only, with
    one new serial number each. Runs inside AddStockView's transaction.
    Returns (product, variant, stock, before, created_variant, changes, serials)."""
    from .costing import average_in, units_in_stock

    product = data["product"]
    variant = data["variant"]
    created = variant is None
    changes = {}
    bought = data.get("cost")
    if data["hsn"] and data["hsn"] != product.hsn:
        changes["hsn"] = (product.hsn, data["hsn"])
        product.hsn = data["hsn"]
    if not product.serial_tracking:
        product.serial_tracking = True  # its units now carry serial numbers
    product.save(update_fields=["hsn", "serial_tracking"])
    if created:
        sibling = product.variants.filter(spec__iexact=data["spec"]).order_by("id").first()
        sell = data["sell_price"]
        variant = Variant.objects.create(
            product=product, spec=data["spec"], colour=data["colour"], sell_price=sell, mrp=data.get("mrp") or sell,
            # the purchase price when entered; else the same specification in another
            # colour costs the same; otherwise the estimate, flagged as such
            cost=bought or (sibling.cost if sibling else round(sell * ESTIMATED_COST_SHARE)),
            cost_estimated=False if bought else (sibling.cost_estimated if sibling else True),
            code=next_code("VC-SKU", Variant, "code"),
        )
    else:
        # prices change only when a new value was entered; invoices keep their own
        prices = {}
        for field in ("sell_price", "mrp"):
            value = data.get(field)
            if value and value != getattr(variant, field):
                prices[field] = (getattr(variant, field), value)
                setattr(variant, field, value)
        if prices:
            variant.save(update_fields=list(prices))
            changes.update(prices)
        if bought:
            # averaged with the units already held (all stores), before these arrive
            changes.update(average_in(variant, units_in_stock(variant), data["quantity"], bought))

    stock, _ = Stock.objects.get_or_create(variant=variant, stock_point=stock_point, defaults={"quantity": 0})
    before = stock.quantity
    update = {"quantity": F("quantity") + data["quantity"]}
    if data["location"].strip():
        update["location"] = data["location"].strip()
    Stock.objects.filter(pk=stock.pk).update(**update)
    stock.refresh_from_db()
    serials = generate_serials(serial_prefix(product.display_name), variant, stock_point, user, data["quantity"])
    return product, variant, stock, before, created, changes, serials
