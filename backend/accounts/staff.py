"""
Staff administration helpers: who may manage whom, role-escalation
checks, session revocation, one-time password-setup links and the audit
log line. Used by accounts.views.UserViewSet and PasswordSetupView.

Nothing here adds tables: a password-setup link is Django's stateless
PasswordResetTokenGenerator (bound to the account's current password hash,
so it stops working the moment a password is set), and sessions are
revoked through simplejwt's existing token blacklist.
"""
import logging

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_encode
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .store_scope import sees_all_stores

audit = logging.getLogger("accounts.audit")

STAFF_ADMIN_PERM = "roles.manage"
SETUP_LINK_HOURS = 24
# Email backends that never leave the machine -- sending through them is
# not a delivery, so a reset email is refused instead of falsely "sent".
LOCAL_EMAIL_BACKENDS = {
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend",
    "django.core.mail.backends.dummy.EmailBackend",
    "django.core.mail.backends.filebased.EmailBackend",
}


class StaffPasswordSetupTokenGenerator(PasswordResetTokenGenerator):
    """Single-use (tied to the password hash) and valid for SETUP_LINK_HOURS."""
    key_salt = "accounts.staff.StaffPasswordSetupTokenGenerator"

    def check_token(self, user, token):
        if not super().check_token(user, token):
            return False
        try:
            issued = base36_to_int(token.split("-")[0])
        except ValueError:
            return False
        return self._num_seconds(self._now()) - issued <= SETUP_LINK_HOURS * 3600


setup_tokens = StaffPasswordSetupTokenGenerator()


def setup_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/set-password/{uid}/{setup_tokens.make_token(user)}"


def email_delivery_configured():
    return settings.EMAIL_BACKEND not in LOCAL_EMAIL_BACKENDS


def is_staff_admin(user):
    return sees_all_stores(user) or user.has_perm_code(STAFF_ADMIN_PERM)


def access_level(user):
    """
    Where the account sits in the existing hierarchy, highest first:
    "superuser" (is_superuser), "superadmin" (the Owner / Super Admin role),
    "admin" (is_staff_admin -- roles.manage) or "staff". Django's is_staff
    plays no part, as in accounts.activity.role_tier.
    """
    if user.is_superuser:
        return "superuser"
    if sees_all_stores(user):
        return "superadmin"
    return "admin" if is_staff_admin(user) else "staff"


def role_codes(role):
    return set(role.permissions.values_list("codename", flat=True)) if role else set()


def actor_codes(actor):
    from .models import Permission
    if actor.is_superuser:
        return set(Permission.objects.values_list("codename", flat=True))
    return role_codes(actor.role)


OUTSOURCE_PERM = "leads.outsource"


def check_outsource(actor, *kinds):
    """Outsourced technicians are added, changed and given jobs by an Admin /
    Super Admin only (leads.outsource) -- store staff never are."""
    if "outsourced" in kinds and not actor.has_perm_code(OUTSOURCE_PERM):
        raise PermissionDenied("Only a Super Admin or Admin can add or change outsourced technicians.")


def check_role_grant(actor, role):
    """Refuse the Owner role, and any role holding a permission the acting
    administrator doesn't hold themselves (no privilege escalation)."""
    if role is None:
        return
    if role.slug == "owner":
        raise PermissionDenied("The Owner role can't be assigned here -- it's tied to the superuser account itself.")
    if sees_all_stores(actor):
        return
    beyond = role_codes(role) - actor_codes(actor)
    if beyond:
        raise PermissionDenied(f"You can't grant permissions you don't hold yourself: {', '.join(sorted(beyond))}.")


def check_can_manage(actor, target, action="manage"):
    """`target` came through the store-scoped queryset already; this adds the
    account-level rules: never yourself, and only a superuser manages a
    superuser / only the Owner manages an all-stores account."""
    if target.pk == actor.pk:
        raise PermissionDenied(f"You can't {action} your own account here.")
    if target.is_superuser and not actor.is_superuser:
        raise PermissionDenied(f"Only a superuser can {action} a superuser account.")
    if sees_all_stores(target) and not sees_all_stores(actor):
        raise PermissionDenied(f"Only the Owner can {action} an Owner account.")


def is_last_owner(user):
    """True if `user` is the only active account that sees every store."""
    from .models import User
    if not (user.is_active and sees_all_stores(user)):
        return False
    others = User.objects.filter(is_active=True).exclude(pk=user.pk)
    return not any(sees_all_stores(u) for u in others.select_related("role"))


def revoke_sessions(user, keep_jti=None):
    """Blacklist every outstanding refresh token of `user` (except `keep_jti`).
    Access tokens can't be revoked; they lapse within ACCESS_TOKEN_LIFETIME."""
    tokens = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    if keep_jti:
        tokens = tokens.exclude(jti=keep_jti)
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)


def log_admin_action(actor, action, target, **details):
    # ids and non-secret facts only -- never passwords, hashes or tokens
    audit.info("staff-admin action=%s actor=%s target=%s %s", action, getattr(actor, "pk", None), target.pk,
               " ".join(f"{k}={v}" for k, v in sorted(details.items())))


def deletable_with_user():
    """Per-account clutter that may go with a deleted account: its own
    notification inbox, hidden-message markers, saved dashboard layout and
    issued (now useless) JWT records. Everything else that points at a user
    -- business records, audit actors, permission-denial logs, admin log --
    blocks deletion instead (see UserViewSet.destroy)."""
    from dashboard.models import DashboardLayout
    from parties.models import MessageHidden

    from .models import StaffNotification
    return {StaffNotification, MessageHidden, DashboardLayout, OutstandingToken}
