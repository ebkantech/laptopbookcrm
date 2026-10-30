"""
The starting set of expense categories. Added only where no category with
the same slug or label (case-insensitive) exists, so re-running or an
existing equivalent never makes a duplicate. "Maintenance" and "Repairs and
Maintenance" are one category here: they record the same kind of cost.
Further categories are added in Django admin.
"""
from django.db import migrations

CATEGORIES = [
    ("rent", "Rent", "operating"),
    ("salary", "Salary", "operating"),
    ("electricity", "Electricity", "operating"),
    ("internet", "Internet", "operating"),
    ("repairs-maintenance", "Repairs & Maintenance", "operating"),
    ("transportation", "Transportation", "operating"),
    ("marketing", "Marketing", "operating"),
    ("office-supplies", "Office Supplies", "operating"),
    ("other", "Other Expenses", "other"),
]


def add_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("accounting", "ExpenseCategory")
    for slug, label, classification in CATEGORIES:
        if ExpenseCategory.objects.filter(slug=slug).exists() or ExpenseCategory.objects.filter(label__iexact=label).exists():
            continue
        ExpenseCategory.objects.create(slug=slug, label=label, classification=classification)


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_expenses"),
    ]

    operations = [
        # never removes categories on the way back: expenses may use them
        migrations.RunPython(add_categories, migrations.RunPython.noop),
    ]
