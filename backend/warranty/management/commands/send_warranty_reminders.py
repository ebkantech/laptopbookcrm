"""Send the 30-day and 7-day 'your warranty is ending' messages. Each is sent once per warranty,
so this is safe to run every day (Render cron / scheduled task): python manage.py send_warranty_reminders"""
from django.core.management.base import BaseCommand

from warranty.services import send_due_reminders


class Command(BaseCommand):
    help = "Send due warranty-expiry reminders to customers."

    def handle(self, *args, **opts):
        self.stdout.write(f"Reminders sent: {send_due_reminders()}")
