"""The four packages and their prices, in whole rupees per duration."""
from django.db import migrations

STARTER = ["inventory", "invoices"]
SERVICE = STARTER + ["leads", "portal", "repairs", "warranty"]
RENTAL = STARTER + ["portal", "rentals"]
FULL = sorted(set(SERVICE + RENTAL + ["accounting", "broadcast", "copilot", "reports"]))

PACKAGES = [
    ("starter", "Starter", STARTER, {1: 0, 3: 0, 6: 2999, 12: 4999}),
    ("service", "Starter + Service", SERVICE, {1: 999, 3: 2499, 6: 3999, 12: 5999}),
    ("rental", "Starter + Rental", RENTAL, {1: 999, 3: 2499, 6: 3999, 12: 5999}),
    ("full", "Full package", FULL, {1: 1999, 3: 3999, 6: 5999, 12: 10999}),
]


def seed(apps, schema_editor):
    Package = apps.get_model("subscriptions", "Package")
    PackagePrice = apps.get_model("subscriptions", "PackagePrice")
    for order, (key, name, modules, prices) in enumerate(PACKAGES):
        package = Package.objects.create(key=key, name=name, modules=modules, sort_order=order)
        for months, amount in prices.items():
            PackagePrice.objects.create(package=package, months=months, amount=amount)


def unseed(apps, schema_editor):
    apps.get_model("subscriptions", "Package").objects.filter(key__in=[row[0] for row in PACKAGES]).delete()


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
