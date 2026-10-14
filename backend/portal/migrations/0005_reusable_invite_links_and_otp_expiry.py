from django.db import migrations, models
from django.db.models import F


def carry_over_legacy_state(apps, schema_editor):
    """
    Under the old rule consumed_at meant "used OR replaced" -- either way
    the link was dead. Keep every such link dead by copying it into
    revoked_at (links are reusable now, so only revoked_at closes one).
    Existing codes keep their old lifetime: the old OTP lived exactly as
    long as the link, so otp_expires_at = expires_at. No expires_at is
    changed, so nothing already expired comes back to life.
    """
    Invite = apps.get_model("portal", "PortalInvite")
    Invite.objects.filter(consumed_at__isnull=False, revoked_at__isnull=True).update(
        revoked_at=F("consumed_at"), revoked_reason="legacy_consumed",
    )
    Invite.objects.exclude(otp_digest="").filter(otp_expires_at__isnull=True).update(
        otp_expires_at=F("expires_at"), otp_issued_at=F("created_at"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0004_remove_portalinvite_otp_code_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="portalinvite",
            name="otp_issued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="portalinvite",
            name="otp_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="portalinvite",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="portalinvite",
            name="revoked_reason",
            field=models.CharField(blank=True, choices=[("replaced", "Replaced by a newer invitation"), ("access_revoked", "Portal access revoked by staff"), ("legacy_consumed", "Used or replaced under the old single-use rule")], max_length=20),
        ),
        migrations.AddField(
            model_name="portalinvite",
            name="last_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="portalinvite",
            name="expires_at",
            field=models.DateTimeField(help_text="When the invitation link itself stops working."),
        ),
        migrations.RunPython(carry_over_legacy_state, migrations.RunPython.noop),
    ]
