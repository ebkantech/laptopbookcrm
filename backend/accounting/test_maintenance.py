"""remove_demo_accounting and backup management commands."""
import tempfile
import zipfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from accounting.models import BankAccount, BankEntry, CashEntry
from crmbook_backend.testing import make_user


class RemoveDemoAccountingTests(TestCase):
    def test_removes_only_the_seeded_samples(self):
        owner = make_user("owner", superuser=True)
        CashEntry.objects.create(date=date(2026, 9, 1), particulars="Opening balance", type="in", amount=42000, by=owner)
        real = CashEntry.objects.create(date=date(2026, 9, 1), particulars="Opening balance", type="in", amount=5000, by=owner)
        hdfc = BankAccount.objects.create(name="HDFC Bank — Current A/c ••4821", opening=612000, is_default=True)
        BankEntry.objects.create(account=hdfc, date=date(2026, 9, 3), particulars="NEFT — Bright Minds School", type="in", amount=209994)

        call_command("remove_demo_accounting", "--dry-run", stdout=StringIO())
        self.assertEqual(CashEntry.objects.count(), 2)

        call_command("remove_demo_accounting", stdout=StringIO())
        self.assertEqual(list(CashEntry.objects.all()), [real])
        self.assertFalse(BankEntry.objects.exists())
        hdfc.refresh_from_db()
        self.assertEqual((hdfc.name, hdfc.opening, hdfc.is_default), ("Business bank account", 0, True))


class BackupTests(TestCase):
    def test_backup_zips_database_and_media_and_keeps_the_newest(self):
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as dest:
            Path(media, "rental-handover").mkdir()
            Path(media, "rental-handover", "front.jpg").write_bytes(b"jpeg")
            with self.settings(MEDIA_ROOT=media):
                for _ in range(3):
                    call_command("backup", "--dir", dest, "--keep", "2", stdout=StringIO(), stderr=StringIO())
            zips = sorted(Path(dest).glob("crmbook-backup-*.zip"))
            self.assertEqual(len(zips), 2)
            names = zipfile.ZipFile(zips[-1]).namelist()
            self.assertIn("media/rental-handover/front.jpg", names)
            self.assertTrue({"db.sqlite3", "data.json", "database.sql"} & set(names))
