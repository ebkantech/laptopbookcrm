import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import LoginAttempt, User
from crmbook_backend.testing import client_for, make_user

BACKEND = Path(__file__).resolve().parent.parent


def login(client, username, password, **extra):
    return client.post("/api/auth/token/", {"username": username, "password": password}, format="json", **extra)


class LoginProtectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("ravi", ["parties.view"])
        self.user.set_password("Correct-horse-battery-9")
        self.user.save()

    def test_spoofed_forwarded_for_no_longer_bypasses_the_rate_limit(self):
        # what reaches Django behind Render: the client's own (fake) value, then the
        # address Render's proxy saw, appended -- only the last one is trusted
        c = APIClient()
        codes = [login(c, "x", "y", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.5").status_code for i in range(7)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5:], [429, 429])

    @override_settings(LOGIN_MAX_FAILURES=3)
    def test_per_account_lockout_from_many_addresses_and_audit(self):
        for i in range(3):
            cache.clear()  # a different address each time: only the account lock applies
            self.assertEqual(login(APIClient(), "ravi", "wrong", REMOTE_ADDR=f"198.51.100.{i}").status_code, 401)
        cache.clear()
        r = login(APIClient(), "ravi", "Correct-horse-battery-9")
        self.assertEqual(r.status_code, 429)  # locked even with the right password
        self.assertIn("Too many failed sign-ins", r.json()["detail"])
        LoginAttempt.objects.filter(username="ravi").update(at=timezone.now() - timedelta(minutes=16))
        cache.clear()
        self.assertEqual(login(APIClient(), "ravi", "Correct-horse-battery-9").status_code, 200)
        reasons = list(LoginAttempt.objects.filter(username="ravi").order_by("at", "id").values_list("success", "reason"))
        self.assertEqual(reasons, [(False, "bad password")] * 3 + [(False, "locked"), (True, "")])

    def test_admin_login_form_is_rate_limited(self):
        c = APIClient()
        codes = [c.post("/admin/login/", {"username": "x", "password": "y"}).status_code for _ in range(7)]
        self.assertEqual(codes[:5], [200] * 5)
        self.assertEqual(codes[5:], [429, 429])

    def test_sign_in_older_than_the_cap_cannot_be_refreshed(self):
        tokens = login(APIClient(), "ravi", "Correct-horse-battery-9").json()
        c = APIClient()
        r = c.post("/api/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)
        old = RefreshToken(r.json()["refresh"])
        self.assertIn("auth_time", old.payload)  # kept across rotation
        stale = RefreshToken.for_user(self.user)
        stale["auth_time"] = int((timezone.now() - timedelta(days=31)).timestamp())
        r = c.post("/api/auth/token/refresh/", {"refresh": str(stale)}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_password_change_kills_existing_access_tokens(self):
        access = login(APIClient(), "ravi", "Correct-horse-battery-9").json()["access"]
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(c.get("/api/users/me/").status_code, 200)
        self.user.set_password("Another-long-pass-42")
        self.user.save()
        self.assertEqual(c.get("/api/users/me/").status_code, 401)


class FailClosedPermissionTests(TestCase):
    def test_unmapped_action_is_refused_not_opened(self):
        staff = client_for(make_user("clerk", ["inventory.edit"]))
        r = staff.post("/api/stock-serials/", {"serial_number": "ZZ00001"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(staff.options("/api/stock-serials/").status_code, 200)


class SecretKeyGuardTests(TestCase):
    def run_settings(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean.update(env)
        return subprocess.run(
            [sys.executable, "-c", "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='crmbook_backend.settings'; django.setup()"],
            cwd=BACKEND, env=clean, capture_output=True, text=True)

    def test_production_refuses_to_start_without_a_real_secret_key(self):
        r = self.run_settings()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must be set", r.stderr)
        self.assertEqual(self.run_settings(DJANGO_SECRET_KEY="x" * 64).returncode, 0, self.run_settings(DJANGO_SECRET_KEY="x" * 64).stderr[-400:])
        self.assertEqual(self.run_settings(DJANGO_DEBUG="True").returncode, 0)
