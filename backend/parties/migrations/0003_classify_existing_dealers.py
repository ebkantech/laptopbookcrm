from django.db import migrations


def classify_existing_dealers(apps, schema_editor):
    Party = apps.get_model("parties", "Party")
    Party.objects.filter(type="Dealer", customer_classification="individual").update(
        customer_classification="dealer"
    )


class Migration(migrations.Migration):
    dependencies = [("parties", "0002_party_customer_classification")]

    operations = [migrations.RunPython(classify_existing_dealers, migrations.RunPython.noop)]
