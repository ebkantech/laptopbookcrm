"""
Back up everything the CRM can't rebuild: the database and the uploaded
files in MEDIA_ROOT (rental handover photos and the like), into one
dated zip. Keeps the newest BACKUP_KEEP zips (default 14) and deletes
older ones.

    python manage.py backup                 # -> BACKUP_DIR (default backend/backups)
    python manage.py backup --dir D:/crm-backups --keep 30

Run it daily -- Windows Task Scheduler, or cron on Linux:
    15 23 * * *  cd /path/to/backend && venv/bin/python manage.py backup

Keep BACKUP_DIR on another disk or a synced folder (Google Drive,
OneDrive): a backup on the same disk dies with it.

What's inside and how to restore:
  SQLite    db.sqlite3  -- stop the server, copy it over backend/db.sqlite3
  Postgres  database.sql (pg_dump, if installed) -- psql -d <db> -f database.sql
            or data.json -- `manage.py migrate` on an empty database, then
            `manage.py loaddata data.json`
  media/    copy its contents back into MEDIA_ROOT
"""
import os
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

PREFIX = "crmbook-backup-"


class Command(BaseCommand):
    help = "Back up the database and uploaded files into a dated zip."

    def add_arguments(self, parser):
        parser.add_argument("--dir", help="Folder to write the backup to (default: BACKUP_DIR or backend/backups).")
        parser.add_argument("--keep", type=int, help="How many backups to keep (default: BACKUP_KEEP or 14).")

    def handle(self, *args, dir=None, keep=None, **options):
        dest = Path(dir or os.environ.get("BACKUP_DIR") or settings.BASE_DIR / "backups")
        keep = keep if keep is not None else int(os.environ.get("BACKUP_KEEP") or 14)
        if keep < 1:
            raise CommandError("--keep must be at least 1.")
        dest.mkdir(parents=True, exist_ok=True)
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        target, n = dest / f"{PREFIX}{stamp}.zip", 1
        while target.exists():  # two runs in the same second
            n += 1
            target = dest / f"{PREFIX}{stamp}-{n}.zip"
        partial = target.with_suffix(".zip.part")

        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, path in self._dump_database(Path(tmp)):
                zf.write(path, name)
            media = Path(settings.MEDIA_ROOT)
            files = 0
            if media.is_dir():
                for path in sorted(media.rglob("*")):
                    if path.is_file():
                        zf.write(path, Path("media") / path.relative_to(media))
                        files += 1
        partial.replace(target)  # only a finished zip ever carries the .zip name

        old = sorted(dest.glob(f"{PREFIX}*.zip"))[:-keep]
        for path in old:
            path.unlink()
        size = target.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f"Backup written: {target} ({size:.1f} MB, {files} uploaded files)"
            + (f"; removed {len(old)} older backup(s)" if old else "")
        ))

    def _dump_database(self, tmp):
        db = settings.DATABASES["default"]
        if db["ENGINE"].endswith("sqlite3"):
            # sqlite's own online backup: a consistent copy even while the
            # server is running
            out = tmp / "db.sqlite3"
            src, dst = sqlite3.connect(str(db["NAME"])), sqlite3.connect(str(out))
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            return [("db.sqlite3", out)]
        if db["ENGINE"].endswith("postgresql"):
            out = tmp / "database.sql"
            env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
            cmd = ["pg_dump", "--no-owner", "-h", db.get("HOST") or "localhost", "-p", str(db.get("PORT") or 5432),
                   "-U", db.get("USER") or "postgres", "-f", str(out), db["NAME"]]
            try:
                subprocess.run(cmd, env=env, check=True, capture_output=True, timeout=600)
                return [("database.sql", out)]
            except (OSError, subprocess.SubprocessError) as e:
                self.stderr.write(f"pg_dump unavailable or failed ({e}); falling back to a JSON dump.")
        connection.close()
        out = tmp / "data.json"
        call_command(
            "dumpdata", "--natural-foreign", "--natural-primary", "--indent", "1", "-o", str(out),
            "--exclude", "contenttypes", "--exclude", "auth.permission", "--exclude", "sessions",
            "--exclude", "token_blacklist",
        )
        return [("data.json", out)]
