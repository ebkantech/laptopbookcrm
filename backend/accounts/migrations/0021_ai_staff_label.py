"""The staff assistant is now called AI-Staff: the Roles screen shows this description."""
from django.db import migrations

CODENAME = "copilot.use"


def rename(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).update(description="Use AI-Staff")


def restore(apps, schema_editor):
    apps.get_model("accounts", "Permission").objects.filter(codename=CODENAME).update(description="Use the staff Copilot assistant")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0020_copilot_permission")]
    operations = [migrations.RunPython(rename, restore)]
