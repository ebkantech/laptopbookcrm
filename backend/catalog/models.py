from django.db import models


class StockPoint(models.Model):
    """A shop or an online channel -- every place stock can physically or notionally sit."""
    SHOP, ONLINE = "shop", "online"
    KIND_CHOICES = [(SHOP, "Shop"), (ONLINE, "Online")]

    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    # Printed as the "sold from" block on invoices raised at this
    # shop/channel. GSTIN only when this branch is registered separately;
    # blank falls back to the business-wide BUSINESS_GSTIN setting.
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    # Inactive = no NEW operations here (sales, repairs, rentals, stock in /
    # out, staff assignment) -- see catalog.status. Its history, stock and
    # staff links are untouched, and it can be reactivated at any time.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    """A model of laptop (or an accessory bundle) -- carries its own product ID and HSN if one applies."""
    LAPTOP, CHARGER, SSD, RAM, ACCESSORIES, OTHER = "laptop", "charger", "ssd", "ram", "accessories", "other"
    CATEGORY_CHOICES = [
        (LAPTOP, "Laptop"), (CHARGER, "Charger"), (SSD, "SSD"), (RAM, "RAM"), (ACCESSORIES, "Accessories"), (OTHER, "Other"),
    ]

    # Set by Inventory -> Add stock -> New product (catalog.new_product);
    # blank on products created before categories existed.
    # db_default: rows inserted by code that predates these columns still get a value
    # a ProductCategory key -- the list is edited at run time (Inventory ->
    # Add stock -> Edit categories); CATEGORY_CHOICES are only the starting six
    category = models.CharField(max_length=20, blank=True, db_index=True, default="", db_default="")
    brand = models.CharField(max_length=40, blank=True)
    model_name = models.CharField(max_length=80)
    processor = models.CharField(max_length=40, blank=True)
    hsn = models.CharField(max_length=12, blank=True, help_text="Leave blank if no HSN applies -- product_code covers it instead.")
    condition = models.CharField(max_length=20, default="New")
    product_code = models.CharField(max_length=32, unique=True, help_text="VC-LAP-#### / VC-ACC-#### -- generated at creation.")
    description = models.TextField(blank=True, default="", db_default="")
    # The category's own specifications, e.g. {"ram": "16GB", "storage": "512GB SSD"}
    # for a laptop or {"wattage": "65W"} for a charger -- keys per category
    # are listed in catalog.new_product.CATEGORY_FIELDS.
    specs = models.JSONField(default=dict, blank=True, db_default=models.Value({}, output_field=models.JSONField()))
    # True: every unit is recorded with its own serial number (StockSerial).
    serial_tracking = models.BooleanField(default=False, db_default=False)

    class Meta:
        ordering = ["brand", "model_name"]

    def __str__(self):
        return f"{self.brand} {self.model_name}".strip()

    @property
    def display_name(self):
        return f"{self.brand} {self.model_name}".strip() if self.brand and self.brand != "\u2014" else self.model_name


class Variant(models.Model):
    """A specific SKU of a product -- its own unique code, its own price."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    code = models.CharField(max_length=32, unique=True)
    spec = models.CharField(max_length=80)
    # Typed in by staff (Add stock), never picked from a list. A product in a
    # new colour is a new variant of the same product, so existing units
    # keep their own colour. Blank on variants recorded before colours.
    colour = models.CharField(max_length=40, blank=True, default="", db_default="")
    mrp = models.PositiveIntegerField()
    sell_price = models.PositiveIntegerField()
    # Purchase cost per unit -- the weighted average of what was paid
    # (catalog.costing). Profit & Loss locks it onto each invoice line at sale.
    cost = models.PositiveIntegerField()
    # True while `cost` is only the automatic guess (78% of the selling price)
    # because no purchase cost was entered: such profit is an estimate.
    cost_estimated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.code} -- {self.spec}"

    @property
    def total_stock(self):
        return sum(s.quantity for s in self.stock.all())


class Stock(models.Model):
    """Shared stock: one row per (variant, stock point). This is what makes stock 'shared' across shops and channels."""
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name="stock")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.CASCADE, related_name="stock")
    quantity = models.PositiveIntegerField(default=0)
    # Where inside this shop/warehouse the units physically sit, so staff
    # can find them -- free text since every shop labels its racks
    # differently, e.g. "Rack A / Shelf 3" or "Back store, bin 12".
    location = models.CharField(max_length=80, blank=True)

    class Meta:
        unique_together = [("variant", "stock_point")]

    def __str__(self):
        return f"{self.variant.code} @ {self.stock_point.name}: {self.quantity}"


class Part(models.Model):
    """A repair part, mapped to the brands it fits -- used by the Repairs module."""
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    compatible_brands = models.JSONField(default=list, blank=True, help_text="List of brand names this part fits.")
    cost = models.PositiveIntegerField(default=0, help_text="Purchase cost per unit; 0 = not entered yet.")

    def __str__(self):
        return self.name


class PartStock(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="stock")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.CASCADE, related_name="part_stock")
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("part", "stock_point")]


class Service(models.Model):
    """A line of repair work -- Hardware or Software segment, with an optional linked Part."""
    HARDWARE, SOFTWARE = "Hardware", "Software"
    SEGMENT_CHOICES = [(HARDWARE, "Hardware"), (SOFTWARE, "Software")]

    slug = models.SlugField(max_length=32, unique=True)
    label = models.CharField(max_length=80)
    segment = models.CharField(max_length=10, choices=SEGMENT_CHOICES)
    charge = models.PositiveIntegerField()
    part = models.ForeignKey(Part, on_delete=models.SET_NULL, null=True, blank=True, related_name="services")

    def __str__(self):
        return self.label


class StockSerial(models.Model):
    """
    One serial-numbered unit received into stock (a product with
    serial_tracking), recorded by Inventory -> Add stock. A serial number
    is unique across the business -- here and among rental devices
    (rentals.RentalAsset.serial_number) -- so the same unit can't be booked in twice.
    """
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="serials")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="serials")
    serial_number = models.CharField(max_length=80, unique=True)
    received_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="stock_serials_received")
    received_at = models.DateTimeField(auto_now_add=True)

    # Where the unit is in its life. Only IN_STOCK units can be sold, rented or written off.
    IN_STOCK, SOLD, RENTED, RETURNED, WRITTEN_OFF = "in_stock", "sold", "rented", "returned", "written_off"
    STATUS_CHOICES = [(IN_STOCK, "In stock"), (SOLD, "Sold"), (RENTED, "On rent"),
                      (RETURNED, "Returned, not restocked"), (WRITTEN_OFF, "Written off")]
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=IN_STOCK, db_index=True)
    # the sale line it went out on (kept after a return, for the history)
    invoice_item = models.ForeignKey("sales.InvoiceItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="serials")
    sold_at = models.DateTimeField(null=True, blank=True)
    # which supplier bill this unit came on (set when stock is added with a
    # supplier, or tagged later for stock already held) -- profit per supplier
    purchase = models.ForeignKey("catalog.Purchase", on_delete=models.SET_NULL, null=True, blank=True, related_name="units")

    class Meta:
        ordering = ["received_at", "id"]

    def __str__(self):
        return f"{self.serial_number} ({self.variant.code} @ {self.stock_point.name})"


class SerialEvent(models.Model):
    """One step in a serial-numbered unit's life -- what the trace shows."""
    RECEIVED, SOLD, SALE_CANCELLED, RETURNED, RENTED, BACK_FROM_RENT, WRITTEN_OFF = (
        "received", "sold", "sale_cancelled", "returned", "rented", "back_from_rent", "written_off")
    serial = models.ForeignKey(StockSerial, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=20)
    text = models.CharField(max_length=300, blank=True)
    stock_point = models.ForeignKey(StockPoint, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    invoice = models.ForeignKey("sales.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]


class Purchase(models.Model):
    """
    Stock bought from a supplier: one bill line -- who, what, how many and
    at what price per unit. Recorded with Inventory -> Add stock, or added
    afterwards for stock already held ("tagged"). The units it covers point
    back to it (StockSerial.purchase), so each sale shows which supplier the
    unit came from and what it really earned. A purchase history only: what
    is owed to / paid to suppliers isn't tracked here.
    """
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="purchases")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="purchases")
    stock_point = models.ForeignKey(StockPoint, on_delete=models.PROTECT, related_name="purchases")
    qty = models.PositiveIntegerField()
    unit_cost = models.PositiveIntegerField(help_text="Price paid per unit, in rupees.")
    bill_no = models.CharField(max_length=60, blank=True)
    purchased_on = models.DateField()
    # True when added later for stock that was already on the shelf / sold
    tagged = models.BooleanField(default=False)
    # Settled before it was recorded here (usually old stock tagged later):
    # it adds nothing to what the supplier is owed
    already_paid = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="purchases_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchased_on", "-id"]

    @property
    def amount(self):
        return self.qty * self.unit_cost

    def __str__(self):
        return f"{self.qty} x {self.variant.code} from {self.supplier.name}"


class ProductCategory(models.Model):
    """
    A product category on Inventory -> Add stock (Laptop, Charger, ... or
    anything the business adds, e.g. "Office chair"), with the details its
    form asks for. Edited at run time by an Admin: rename it, add / remove /
    rename fields, make a field required (*) or a fixed choice.

    `key` never changes once created: products store it (Product.category),
    and each field's `key` is what a product's specs are saved under, so
    renaming a category or a field never loses what was recorded.

    fields: [{"key", "label", "type": "text"|"choice"|"long", "required",
              "options": [...], "suggest": [...], "placeholder", "summary"}]
    `summary` fields make up the variant's spec line ("16GB / 512GB SSD").
    """
    ICONS = ["laptop", "plug", "hard-drive", "memory", "headphones", "package", "monitor", "printer", "smartphone",
             "keyboard", "mouse", "cable", "armchair", "box", "tag", "wrench"]

    key = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=40)
    icon = models.CharField(max_length=20, default="package")
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    name_label = models.CharField(max_length=40, default="Model / product name")
    brand_required = models.BooleanField(default=True)
    show_condition = models.BooleanField(default=False)
    code_prefix = models.CharField(max_length=10, default="VC-ACC")
    fields = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name_plural = "product categories"

    def __str__(self):
        return self.name


class SupplierPayment(models.Model):
    """
    Money paid to a supplier against their bills (catalog.Purchase): one
    cash-book or bank-book "out" entry, posted when it's recorded and never
    edited -- so the cash / bank balance and what the supplier is owed
    always agree. Paying more than is owed leaves an advance with them.
    """
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="supplier_payments")
    amount = models.PositiveIntegerField()
    paid_on = models.DateField()
    method = models.CharField(max_length=40)
    reference = models.CharField(max_length=80, blank=True, help_text="UTR / cheque no. / receipt")
    note = models.CharField(max_length=200, blank=True)
    # the bill it was for, when it was for one in particular
    purchase = models.ForeignKey(Purchase, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="supplier_payments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["paid_on", "id"]

    def __str__(self):
        return f"₹{self.amount} to {self.supplier.name} on {self.paid_on}"
