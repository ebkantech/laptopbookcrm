import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
        ("repairs", "0002_alter_repairinvoice_ticket_repairreopen_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RepairEstimate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveSmallIntegerField()),
                ("is_current", models.BooleanField(default=True)),
                ("customer_name", models.CharField(max_length=120)),
                ("customer_phone", models.CharField(max_length=20)),
                ("device_brand", models.CharField(max_length=40)),
                ("device_model", models.CharField(max_length=80)),
                ("device_serial", models.CharField(blank=True, max_length=60)),
                ("reported_issue", models.TextField()),
                ("currency", models.CharField(default="INR", max_length=3)),
                ("total_amount", models.PositiveIntegerField()),
                ("advance_paid", models.PositiveIntegerField(default=0)),
                ("terms", models.TextField(default="I approve the final repair work and total amount shown in this estimate. Any later change will be coordinated separately with the service centre.")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repair_estimates_created", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="estimates", to="repairs.repairticket")),
            ],
            options={"ordering": ["-version"]},
        ),
        migrations.CreateModel(
            name="RepairApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_hash", models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("expired", "Expired"), ("revoked", "Revoked")], default="pending", max_length=12)),
                ("source", models.CharField(blank=True, choices=[("customer", "Customer via secure link"), ("admin", "Admin on behalf of customer"), ("superadmin", "Super Admin override")], max_length=12)),
                ("sent_to_phone", models.CharField(blank=True, max_length=20)),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repair_approvals_decided", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repair_approvals_requested", to=settings.AUTH_USER_MODEL)),
                ("estimate", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="approvals", to="repairs.repairestimate")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RepairEstimateLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.CharField(max_length=160)),
                ("quantity", models.PositiveSmallIntegerField(default=1)),
                ("unit_price", models.PositiveIntegerField()),
                ("estimate", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="repairs.repairestimate")),
                ("service", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repair_estimate_lines", to="catalog.service")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="RepairTicketEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("ticket_created", "Ticket created"), ("estimate_finalized", "Estimate finalized"), ("approval_link_created", "Approval link created"), ("approval_decided", "Approval decided"), ("stage_changed", "Stage changed"), ("settled", "Settled")], max_length=30)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repair_ticket_events", to=settings.AUTH_USER_MODEL)),
                ("estimate", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="repairs.repairestimate")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="repairs.repairticket")),
            ],
            options={"ordering": ["at", "id"]},
        ),
        migrations.AddConstraint(model_name="repairestimate", constraint=models.UniqueConstraint(fields=("ticket", "version"), name="unique_repair_estimate_version")),
        migrations.AddConstraint(model_name="repairestimate", constraint=models.UniqueConstraint(condition=models.Q(("is_current", True)), fields=("ticket",), name="one_current_repair_estimate")),
        migrations.AddConstraint(model_name="repairapproval", constraint=models.UniqueConstraint(condition=models.Q(("status", "pending")), fields=("estimate",), name="one_pending_repair_approval_link")),
        migrations.AddConstraint(model_name="repairapproval", constraint=models.UniqueConstraint(condition=models.Q(("status", "approved")), fields=("estimate",), name="one_approved_repair_decision")),
        migrations.AddConstraint(model_name="repairestimateline", constraint=models.CheckConstraint(condition=models.Q(("quantity__gt", 0)), name="repair_estimate_quantity_gt_zero")),
    ]
