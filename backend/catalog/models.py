from django.db import models


class StockPoint(models.Model):
    """A shop or an online channel -- every place stock can physically or notionally sit."""
    SHOP, ONLINE = "shop", "online"
    KIND_CHOICES = [(SHOP, "Shop"), (ONLINE, "Online")]

    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    """A model of laptop (or an accessory bundle) -- carries its own product ID and HSN if one applies."""
    brand = models.CharField(max_length=40, blank=True)
    model_name = models.CharField(max_length=80)
    processor = models.CharField(max_length=40, blank=True)
    hsn = models.CharField(max_length=12, blank=True, help_text="Leave blank if no HSN applies -- product_code covers it instead.")
    condition = models.CharField(max_length=20, default="New")
    product_code = models.CharField(max_length=32, unique=True, help_text="VC-LAP-#### / VC-ACC-#### -- generated at creation.")

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
    mrp = models.PositiveIntegerField()
    sell_price = models.PositiveIntegerField()
    cost = models.PositiveIntegerField()

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

    class Meta:
        unique_together = [("variant", "stock_point")]

    def __str__(self):
        return f"{self.variant.code} @ {self.stock_point.name}: {self.quantity}"


class Part(models.Model):
    """A repair part, mapped to the brands it fits -- used by the Repairs module."""
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    compatible_brands = models.JSONField(default=list, blank=True, help_text="List of brand names this part fits.")

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
