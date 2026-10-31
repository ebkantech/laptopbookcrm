"""
Settings > Staff Management: creating staff, editing role / store,
self-service password change, admin password reset (one-time setup link),
deactivation and deletion -- and the authorization around each.
"""
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounting.models import CashEntry
from accounts.models import Permission, Role, User
from catalog.models import StockPoint
from crmbook_backend.testing import client_for, make_user, results

PASSWORD = "safe-test-password"
NEW_PASSWORD = "Quiet-Harbour-2048"


class StaffAdminFixture(TestCase):
    def setUp(self):
        cache.clear()  # login / password-change throttles
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.np = StockPoint.objects.create(slug="np", name="Nehru Place", kind=StockPoint.SHOP)
        self.web = StockPoint.objects.create(slug="web", name="Website", kind=StockPoint.ONLINE)
        self.owner_user = make_user("owner", superuser=True)
        self.owner = client_for(self.owner_user)
        # a store administrator: roles.manage at Karol Bagh only
        self.kb_admin_user = make_user("kb-admin", ["roles.manage", "invoices.view"], stock_point=self.kb)
        self.kb_admin = client_for(self.kb_admin_user)
        self.kb_staff_user = make_user("kb-staff", ["invoices.view"], stock_point=self.kb)
        self.kb_staff = client_for(self.kb_staff_user)
        self.np_staff_user = make_user("np-staff", ["invoices.view"], stock_point=self.np)
        self.sales_role = Role.objects.create(slug="sales-test", label="Sales test")
        self.sales_role.permissions.add(Permission.objects.get(codename="invoices.view"))
        self.big_role = Role.objects.create(slug="big-test", label="Big test")
        self.big_role.permissions.add(Permission.objects.get_or_create(codename="cashbook.edit", defaults={"description": "x"})[0])

    def new_staff(self, client, **extra):
        body = {"username": "new.joiner", "first_name": "New", "last_name": "Joiner", "email": "new@example.com",
                "role": self.sales_role.id, "stock_point": self.kb.id, **extra}
        return client.post("/api/users/", body, format="json")


class CreateStaffTests(StaffAdminFixture):
    def test_owner_creates_staff_with_role_store_and_no_password_until_setup(self):
        response = self.new_staff(self.owner, stock_point=self.np.id)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["username"], body["role"], body["stock_point"], body["password_set"]), ("new.joiner", self.sales_role.id, self.np.id, False))
        self.assertNotIn("password", body)
        user = User.objects.get(username="new.joiner")
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser)

    def test_admin_can_set_a_validated_initial_password_that_is_never_returned(self):
        weak = self.new_staff(self.owner, password="12345", password_confirm="12345")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("password", weak.json())
        mismatch = self.new_staff(self.owner, password=NEW_PASSWORD, password_confirm=NEW_PASSWORD + "x")
        self.assertIn("password_confirm", mismatch.json())
        ok = self.new_staff(self.owner, password=NEW_PASSWORD, password_confirm=NEW_PASSWORD)
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertNotIn(NEW_PASSWORD, ok.content.decode())
        self.assertTrue(User.objects.get(username="new.joiner").check_password(NEW_PASSWORD))

    def test_duplicate_username_and_email_are_rejected(self):
        self.assertEqual(self.new_staff(self.owner).status_code, 201)
        dup = self.new_staff(self.owner, username="NEW.JOINER", email="other@example.com")
        self.assertIn("username", dup.json())
        dup_email = self.new_staff(self.owner, username="someone.else", email="NEW@example.com")
        self.assertIn("email", dup_email.json())
        bad_email = self.new_staff(self.owner, username="third", email="not-an-email")
        self.assertIn("email", bad_email.json())

    def test_privileged_fields_cannot_be_mass_assigned(self):
        response = self.new_staff(self.owner, is_superuser=True, is_staff=True)
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="new.joiner")
        self.assertEqual((user.is_superuser, user.is_staff), (False, False))

    def test_owner_role_and_online_channels_cannot_be_assigned(self):
        owner_role = Role.objects.get_or_create(slug="owner", defaults={"label": "Owner"})[0]
        self.assertEqual(self.new_staff(self.owner, role=owner_role.id).status_code, 403)
        self.assertIn("stock_point", self.new_staff(self.owner, stock_point=self.web.id).json())

    def test_store_admin_creates_staff_only_at_their_store_and_only_with_their_permissions(self):
        self.assertEqual(self.new_staff(self.kb_admin, stock_point=self.np.id).status_code, 403)
        self.assertEqual(self.new_staff(self.kb_admin, stock_point=None).status_code, 403)
        self.assertEqual(self.new_staff(self.kb_admin, role=self.big_role.id).status_code, 403)  # escalation
        ok = self.new_staff(self.kb_admin)
        self.assertEqual(ok.status_code, 201, ok.content)
        no_store_given = self.new_staff(self.kb_admin, username="second", email="second@example.com")
        no_store_given_body = {k: v for k, v in no_store_given.json().items()}
        self.assertEqual(no_store_given_body["stock_point"], self.kb.id)

    def test_ordinary_staff_cannot_create_accounts(self):
        self.assertEqual(self.new_staff(self.kb_staff).status_code, 403)
        self.assertFalse(User.objects.filter(username="new.joiner").exists())


class DirectoryTests(StaffAdminFixture):
    def test_owner_sees_everyone_store_admin_their_store_staff_no_contact_details(self):
        self.assertEqual({u["username"] for u in results(self.owner.get("/api/users/"))},
                         {"owner", "kb-admin", "kb-staff", "np-staff"})
        self.assertEqual({u["username"] for u in results(self.kb_admin.get("/api/users/"))}, {"kb-admin", "kb-staff"})
        staff_view = results(self.kb_staff.get("/api/users/"))
        colleague = next(u for u in staff_view if u["username"] == "kb-admin")
        self.assertNotIn("email", colleague)
        self.assertNotIn("phone", colleague)
        self.assertNotIn("password_set", colleague)
        for row in results(self.owner.get("/api/users/")):
            self.assertNotIn("password", row)


class EditStaffTests(StaffAdminFixture):
    def test_store_admin_edits_their_staff_but_not_store_or_escalated_role(self):
        url = f"/api/users/{self.kb_staff_user.id}/"
        self.assertEqual(self.kb_admin.patch(url, {"first_name": "Renamed"}, format="json").status_code, 200)
        self.assertEqual(self.kb_admin.patch(url, {"stock_point": self.np.id}, format="json").status_code, 403)
        self.assertEqual(self.kb_admin.patch(url, {"role": self.big_role.id}, format="json").status_code, 403)
        self.assertEqual(self.kb_admin.patch(f"/api/users/{self.np_staff_user.id}/", {"first_name": "x"}, format="json").status_code, 404)
        self.assertEqual(self.kb_admin.post(f"/api/users/{self.kb_staff_user.id}/set-role/", {"role": self.big_role.slug}, format="json").status_code, 403)

    def test_staff_cannot_escalate_or_move_themselves(self):
        me = f"/api/users/{self.kb_staff_user.id}/"
        self.assertEqual(self.kb_staff.patch(me, {"role": self.big_role.id}, format="json").status_code, 403)
        self.assertEqual(self.kb_staff.patch(me, {"stock_point": self.np.id}, format="json").status_code, 403)
        # even a store admin can't change their own role or store
        self.assertEqual(self.kb_admin.patch(f"/api/users/{self.kb_admin_user.id}/", {"role": self.sales_role.id}, format="json").status_code, 403)
        self.kb_staff_user.refresh_from_db()
        self.assertEqual((self.kb_staff_user.stock_point, self.kb_staff_user.role.slug.startswith("test-role")), (self.kb, True))

    def test_owner_moves_staff_between_stores(self):
        response = self.owner.patch(f"/api/users/{self.kb_staff_user.id}/", {"stock_point": self.np.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stock_point_name"], "Nehru Place")

    def test_admin_cannot_touch_owner_accounts(self):
        self.assertEqual(self.kb_admin.patch(f"/api/users/{self.owner_user.id}/", {"first_name": "x"}, format="json").status_code, 404)


class ChangeOwnPasswordTests(StaffAdminFixture):
    url = "/api/users/me/change-password/"

    def body(self, current=PASSWORD, new=NEW_PASSWORD, confirm=None):
        return {"current_password": current, "new_password": new, "confirm_password": confirm or new}

    def test_change_with_correct_current_password_signs_out_other_sessions(self):
        other_session = RefreshToken.for_user(self.kb_staff_user)
        response = self.kb_staff.post(self.url, self.body(), format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("access", response.json())
        self.kb_staff_user.refresh_from_db()
        self.assertTrue(self.kb_staff_user.check_password(NEW_PASSWORD))
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=other_session["jti"]).exists())
        # the old refresh token can't be exchanged any more
        self.assertEqual(APIClient().post("/api/auth/token/refresh/", {"refresh": str(other_session)}, format="json").status_code, 401)
        # and the new password logs in
        self.assertEqual(APIClient().post("/api/auth/token/", {"username": "kb-staff", "password": NEW_PASSWORD}, format="json").status_code, 200)

    def test_wrong_current_mismatch_and_weak_passwords_are_rejected(self):
        self.assertIn("current_password", self.kb_staff.post(self.url, self.body(current="nope"), format="json").json())
        self.assertIn("confirm_password", self.kb_staff.post(self.url, self.body(confirm="Different-Pass-9999"), format="json").json())
        self.assertIn("new_password", self.kb_staff.post(self.url, self.body(new="password1"), format="json").json())
        self.assertIn("new_password", self.kb_staff.post(self.url, self.body(new="12345678901"), format="json").json())
        self.kb_staff_user.refresh_from_db()
        self.assertTrue(self.kb_staff_user.check_password(PASSWORD))

    def test_cannot_change_someone_else_by_sending_their_id(self):
        response = self.kb_staff.post(self.url, {**self.body(), "user": self.np_staff_user.id, "id": self.np_staff_user.id}, format="json")
        self.assertEqual(response.status_code, 200)
        self.np_staff_user.refresh_from_db()
        self.assertTrue(self.np_staff_user.check_password(PASSWORD))

    def test_needs_authentication(self):
        self.assertEqual(APIClient().post(self.url, self.body(), format="json").status_code, 401)


class ResetPasswordTests(StaffAdminFixture):
    def reset(self, client, user, delivery="link"):
        return client.post(f"/api/users/{user.id}/reset-password/", {"delivery": delivery}, format="json")

    def test_link_reset_affects_only_the_selected_account_and_link_is_single_use(self):
        response = self.reset(self.owner, self.kb_staff_user)
        self.assertEqual(response.status_code, 200, response.content)
        link = response.json()["setup_url"]
        self.kb_staff_user.refresh_from_db()
        self.np_staff_user.refresh_from_db()
        self.assertFalse(self.kb_staff_user.has_usable_password())
        self.assertTrue(self.np_staff_user.check_password(PASSWORD))  # untouched

        uid, token = link.rstrip("/").split("/")[-2:]
        public = APIClient()
        url = f"/api/auth/password-setup/{uid}/{token}/"
        self.assertEqual(public.get(url).json()["username"], "kb-staff")
        self.assertIn("new_password", public.post(url, {"new_password": "short", "confirm_password": "short"}, format="json").json())
        ok = public.post(url, {"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.kb_staff_user.refresh_from_db()
        self.assertTrue(self.kb_staff_user.check_password(NEW_PASSWORD))
        # single use: the token was bound to the old hash
        self.assertEqual(public.post(url, {"new_password": "Another-Pass-7788", "confirm_password": "Another-Pass-7788"}, format="json").status_code, 400)

    def test_tampered_or_foreign_tokens_are_rejected(self):
        link = self.reset(self.owner, self.kb_staff_user).json()["setup_url"]
        uid, token = link.rstrip("/").split("/")[-2:]
        other_uid = link.split("/")[-2]  # same uid
        self.assertEqual(APIClient().get(f"/api/auth/password-setup/{uid}/{token}x/").status_code, 400)
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        np_uid = urlsafe_base64_encode(force_bytes(self.np_staff_user.pk))
        self.assertEqual(APIClient().get(f"/api/auth/password-setup/{np_uid}/{token}/").status_code, 400)
        self.assertTrue(other_uid)

    def test_email_reset_is_refused_without_a_real_email_provider(self):
        self.kb_staff_user.email = "kb@example.com"
        self.kb_staff_user.save()
        response = self.reset(self.owner, self.kb_staff_user, "email")
        self.assertEqual((response.status_code, response.json()["code"]), (400, "email_not_configured"))
        self.kb_staff_user.refresh_from_db()
        self.assertTrue(self.kb_staff_user.check_password(PASSWORD))  # nothing changed

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_email_reset_reports_sent_only_when_the_provider_accepts_it(self):
        self.kb_staff_user.email = "kb@example.com"
        self.kb_staff_user.save()
        with mock.patch("django.core.mail.send_mail", return_value=1) as send:
            response = self.reset(self.owner, self.kb_staff_user, "email")
        self.assertEqual((response.status_code, response.json()["status"]), (200, "sent"))
        self.assertNotIn("setup_url", response.json())
        self.assertEqual(send.call_args.kwargs["recipient_list"], ["kb@example.com"])
        with mock.patch("django.core.mail.send_mail", side_effect=OSError("smtp down")):
            failed = self.reset(self.owner, self.kb_staff_user, "email")
        self.assertEqual((failed.status_code, failed.json()["code"]), (502, "email_failed"))

    def test_unauthorized_resets_are_refused(self):
        self.assertEqual(self.reset(self.kb_staff, self.np_staff_user).status_code, 403)
        self.assertEqual(self.reset(self.kb_staff, self.kb_admin_user).status_code, 403)
        self.assertEqual(self.reset(self.kb_admin, self.np_staff_user).status_code, 404)  # other store
        self.assertEqual(self.reset(self.kb_admin, self.owner_user).status_code, 404)
        self.assertEqual(self.reset(self.kb_admin, self.kb_admin_user).status_code, 403)  # self: use change-password
        for user in (self.np_staff_user, self.kb_admin_user, self.owner_user):
            user.refresh_from_db()
            self.assertTrue(user.has_usable_password())

    def test_reset_signs_out_existing_sessions(self):
        session = RefreshToken.for_user(self.kb_staff_user)
        self.reset(self.kb_admin, self.kb_staff_user)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=session["jti"]).exists())


class DeactivateAndDeleteTests(StaffAdminFixture):
    def test_self_deletion_and_last_owner_deletion_are_blocked(self):
        self.assertEqual(self.owner.delete(f"/api/users/{self.owner_user.id}/").status_code, 403)
        second_owner = make_user("second-owner", superuser=True)
        # the original owner may delete a second superuser with no history...
        self.assertEqual(self.owner.delete(f"/api/users/{second_owner.id}/").status_code, 204)
        # ...but never the last active one (here: via another superuser)
        other = client_for(make_user("third-owner", superuser=True))
        User.objects.filter(pk=self.owner_user.pk).update(is_active=True)
        User.objects.exclude(pk__in=[self.owner_user.pk]).filter(is_superuser=True).update(is_active=False)
        other_user = User.objects.get(username="third-owner")
        other = client_for(other_user)
        self.assertEqual(other.delete(f"/api/users/{self.owner_user.id}/").status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.owner_user.pk).exists())

    def test_only_the_owner_deletes_and_staff_with_history_are_kept(self):
        self.assertEqual(self.kb_admin.delete(f"/api/users/{self.kb_staff_user.id}/").status_code, 403)
        self.assertEqual(self.kb_staff.delete(f"/api/users/{self.kb_admin_user.id}/").status_code, 403)
        entry = CashEntry.objects.create(date=date.today(), particulars="Till", type=CashEntry.IN, amount=1, by=self.kb_staff_user)
        blocked = self.owner.delete(f"/api/users/{self.kb_staff_user.id}/")
        self.assertEqual((blocked.status_code, blocked.json()["code"]), (409, "has_history"))
        self.assertTrue(User.objects.filter(pk=self.kb_staff_user.pk).exists())
        self.assertTrue(CashEntry.objects.filter(pk=entry.pk).exists())

    def test_staff_without_history_can_be_deleted_by_the_owner(self):
        fresh = make_user("fresh-hire", stock_point=self.kb)
        RefreshToken.for_user(fresh)  # an issued token doesn't count as history
        self.assertEqual(self.owner.delete(f"/api/users/{fresh.id}/").status_code, 204)
        self.assertFalse(User.objects.filter(pk=fresh.pk).exists())

    def test_deactivation_signs_out_blocks_login_and_protects_last_owner(self):
        session = RefreshToken.for_user(self.kb_staff_user)
        response = self.kb_admin.post(f"/api/users/{self.kb_staff_user.id}/set-active/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=session["jti"]).exists())
        self.assertEqual(APIClient().post("/api/auth/token/", {"username": "kb-staff", "password": PASSWORD}, format="json").status_code, 401)
        self.assertEqual(self.kb_admin.post(f"/api/users/{self.kb_admin_user.id}/set-active/", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(self.kb_staff.post(f"/api/users/{self.kb_admin_user.id}/set-active/", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(self.owner.post(f"/api/users/{self.owner_user.id}/set-active/", {"is_active": False}, format="json").status_code, 403)
        self.assertTrue(OutstandingToken.objects.exists())


class ExistingFlowsStillWorkTests(StaffAdminFixture):
    def test_login_jwt_and_store_scope_unchanged(self):
        login = APIClient().post("/api/auth/token/", {"username": "kb-staff", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        self.assertEqual(client.get("/api/users/me/").json()["stock_point"], self.kb.id)
        self.assertEqual([sp["id"] for sp in results(client.get("/api/stock-points/"))], [self.kb.id])
        self.assertEqual(client.get("/api/tickets/").status_code, 403)  # role still lacks repairs.view
