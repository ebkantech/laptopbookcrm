from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission

from parties.models import Party

SALT = "crmbook.portal.session"
MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # a portal session is good for 7 days after verifying OTP


def issue_portal_token(party: Party) -> str:
    # issued_at is carried in the payload (not just relied on via
    # signing's own timestamp, which loads() doesn't expose) so
    # resolve_portal_token can tell a token issued before a revocation
    # apart from one issued after -- see Party.portal_access_revoked_at.
    return signing.dumps({"party_id": party.id, "issued_at": timezone.now().timestamp()}, salt=SALT)


def resolve_portal_token(token: str) -> Party | None:
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    party = Party.objects.filter(pk=data.get("party_id")).first()
    if not party:
        return None
    issued_at = data.get("issued_at")
    if party.portal_access_revoked_at and issued_at is not None:
        if issued_at <= party.portal_access_revoked_at.timestamp():
            return None  # token predates the revocation -- treat exactly like an invalid token
    return party


class PortalTokenAuthentication(BaseAuthentication):
    """
    Customers are Party records, not accounts.User rows -- there's no
    Django auth user to authenticate as, so this is a deliberately
    separate, much smaller auth scheme from staff JWT. A valid token
    sets request.party; it never sets request.user, which is exactly
    what keeps a portal session from ever being usable against any
    staff-facing endpoint (those all require request.user via
    IsAuthenticated, which a portal session never satisfies).
    """
    keyword = "Portal"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(f"{self.keyword} "):
            return None
        token = header[len(self.keyword) + 1:]
        party = resolve_portal_token(token)
        if not party:
            return None
        request.party = party
        return (None, token)  # no Django user -- (user, auth) tuple with user=None


class IsPortalCustomer(BasePermission):
    def has_permission(self, request, view):
        return getattr(request, "party", None) is not None
