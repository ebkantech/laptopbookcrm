from django.conf import settings
from django.db import models
from django.db.models import Q


class DashboardWidget(models.Model):
    """
    Catalog of every element the Dashboard page can show -- one row per
    KPI card, chart, list or panel. Describes *what* an element is and
    which slice of the /api/dashboard/summary/ payload it reads; where it
    sits and how big it is for a given person lives on
    DashboardLayoutItem below.

    `section` ties the widget to the same per-role gate DashboardView
    already applies (stock / sales / repairs / rentals), so a widget is
    only ever offered to someone whose role can see its data. The rows
    themselves are seeded by migration 0002 to match the elements the
    frontend renders today.
    """
    KPI = "kpi"
    CHART = "chart"
    LIST = "list"
    TABLE = "table"
    PANEL = "panel"
    KIND_CHOICES = [
        (KPI, "KPI card"),
        (CHART, "Chart"),
        (LIST, "List"),
        (TABLE, "Table"),
        (PANEL, "Panel"),
    ]

    STOCK = "stock"
    SALES = "sales"
    REPAIRS = "repairs"
    RENTALS = "rentals"
    SECTION_CHOICES = [
        (STOCK, "Stock"),
        (SALES, "Sales"),
        (REPAIRS, "Repairs"),
        (RENTALS, "Rentals"),
    ]

    LINE = "line"
    BAR = "bar"
    DONUT = "donut"
    CHART_TYPE_CHOICES = [
        (LINE, "Line"),
        (BAR, "Bar"),
        (DONUT, "Donut"),
    ]

    # Width/height are in grid units on a 12-column dashboard grid.
    GRID_COLUMNS = 12

    key = models.SlugField(max_length=64, unique=True, help_text="Stable identifier the frontend renders by, e.g. 'kpi-sales-revenue'.")
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    chart_type = models.CharField(max_length=10, choices=CHART_TYPE_CHOICES, blank=True, help_text="Only for kind=chart.")
    section = models.CharField(max_length=10, choices=SECTION_CHOICES)
    data_keys = models.JSONField(default=list, blank=True, help_text="Keys of the dashboard summary response this widget reads.")
    respects_filters = models.BooleanField(default=True, help_text="Whether the date/channel filter bar changes this widget's figures.")
    link_page = models.CharField(max_length=32, blank=True, help_text="Page the widget's 'View …' link opens, e.g. 'inventory'.")
    default_order = models.PositiveSmallIntegerField(default=0)
    default_width = models.PositiveSmallIntegerField(default=3)
    default_height = models.PositiveSmallIntegerField(default=1)
    default_settings = models.JSONField(default=dict, blank=True, help_text="Per-widget options, e.g. {\"limit\": 6}.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["default_order", "key"]
        constraints = [
            models.CheckConstraint(
                condition=Q(default_width__gte=1) & Q(default_width__lte=12),
                name="dashboardwidget_width_in_grid",
            ),
            models.CheckConstraint(
                condition=Q(default_height__gte=1),
                name="dashboardwidget_height_positive",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.key})"


class DashboardLayout(models.Model):
    """
    An arrangement of widgets, owned by exactly one Role (the default for
    everyone holding it) or one User (a personal override). Lookup order
    for the signed-in user is: their own layout, then their role's, then
    the catalog defaults -- see dashboard.layouts.effective_layout().
    """
    name = models.CharField(max_length=64, blank=True)
    role = models.OneToOneField("accounts.Role", on_delete=models.CASCADE, null=True, blank=True, related_name="dashboard_layout")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="dashboard_layout")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(role__isnull=False) & Q(user__isnull=True)) | (Q(role__isnull=True) & Q(user__isnull=False)),
                name="dashboardlayout_single_owner",
            ),
        ]

    def __str__(self):
        owner = f"role {self.role}" if self.role_id else f"user {self.user}"
        return self.name or f"Dashboard layout for {owner}"


class DashboardLayoutItem(models.Model):
    """One widget's placement inside a layout: order, size, visibility and options."""
    layout = models.ForeignKey(DashboardLayout, on_delete=models.CASCADE, related_name="items")
    widget = models.ForeignKey(DashboardWidget, on_delete=models.CASCADE, related_name="placements")
    position = models.PositiveSmallIntegerField(default=0)
    width = models.PositiveSmallIntegerField(default=3)
    height = models.PositiveSmallIntegerField(default=1)
    is_visible = models.BooleanField(default=True)
    settings = models.JSONField(default=dict, blank=True, help_text="Overrides merged over the widget's default_settings.")

    class Meta:
        ordering = ["layout", "position"]
        unique_together = [("layout", "widget")]
        constraints = [
            models.CheckConstraint(
                condition=Q(width__gte=1) & Q(width__lte=12),
                name="dashboardlayoutitem_width_in_grid",
            ),
            models.CheckConstraint(
                condition=Q(height__gte=1),
                name="dashboardlayoutitem_height_positive",
            ),
        ]

    def __str__(self):
        return f"{self.layout} · {self.widget.key} @ {self.position}"
