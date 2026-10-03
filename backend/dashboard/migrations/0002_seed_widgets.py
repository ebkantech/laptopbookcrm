from django.db import migrations

# The elements Dashboard.jsx renders today, in on-screen order. Widths
# are on a 12-column grid: KPI cards 3, half-width charts/lists 6,
# full-width panels 12.
WIDGETS = [
    # key, title, kind, chart_type, section, data_keys, respects_filters, link_page, width, settings
    ("kpi-sales-revenue", "Sales revenue, paid", "kpi", "", "sales", ["revenue_paid"], True, "", 3, {}),
    ("kpi-repair-revenue", "Repair revenue, paid", "kpi", "", "repairs", ["repair_revenue_paid", "repair_invoice_count"], True, "", 3, {}),
    ("kpi-pending-collections", "Pending collections", "kpi", "", "sales", ["pending_collections", "open_invoice_count"], True, "", 3, {}),
    ("kpi-stock-on-hand", "Stock on hand", "kpi", "", "stock", ["total_stock_units", "stock_value"], True, "", 3, {}),
    ("kpi-low-stock", "Low stock alerts", "kpi", "", "stock", ["low_stock_count"], True, "", 3, {"threshold": 4}),
    ("kpi-rentals-at-risk", "Rentals at churn risk", "kpi", "", "rentals", ["rentals_at_risk", "rental_count", "rental_device_count"], False, "", 3, {}),
    ("kpi-rentals-pending-approval", "Rentals pending approval", "kpi", "", "rentals", ["rentals_pending_approval"], False, "", 3, {"hide_when_zero": True}),
    ("kpi-repairs-overdue", "Overdue repair tickets", "kpi", "", "repairs", ["repair_overdue_count"], False, "", 3, {"hide_when_zero": True}),
    ("chart-monthly-revenue", "Revenue by month — sales & repairs, paid", "chart", "line", "sales", ["monthly_revenue"], False, "", 6, {"months": 6}),
    ("list-low-stock", "Low stock, act soon", "list", "", "stock", ["low_stock"], True, "inventory", 6, {"limit": 6}),
    ("panel-repair-stages", "Ticket queue by stage", "panel", "", "repairs", ["repair_stage_counts"], False, "repairs", 12, {}),
    ("list-churn-leaderboard", "Customer churn risk — rentals", "list", "", "rentals", ["churn_leaderboard"], False, "rentals", 12, {"limit": 5}),
    ("panel-recurring-issues", "Recurring issues on rented laptops", "panel", "", "rentals", ["recurring_issues_by_unit", "recurring_issues_by_model"], False, "rentals", 12, {}),
    ("chart-sales-by-channel", "Paid revenue by channel", "chart", "bar", "sales", ["channel_sales"], True, "", 12, {}),
]


def seed(apps, schema_editor):
    DashboardWidget = apps.get_model("dashboard", "DashboardWidget")
    for order, (key, title, kind, chart_type, section, data_keys, respects_filters, link_page, width, settings) in enumerate(WIDGETS, start=1):
        DashboardWidget.objects.update_or_create(
            key=key,
            defaults={
                "title": title, "kind": kind, "chart_type": chart_type, "section": section,
                "data_keys": data_keys, "respects_filters": respects_filters, "link_page": link_page,
                "default_order": order * 10, "default_width": width, "default_settings": settings,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("dashboard", "DashboardWidget").objects.filter(key__in=[w[0] for w in WIDGETS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
