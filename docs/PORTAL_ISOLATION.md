# Portal isolation — architecture note

Task 5 of the Phase 2 Build Pipeline (Sep 25, 2026) asked for a written
sign-off that the customer portal is genuinely separate from the staff
app, not just presented separately in the UI. This is that sign-off,
current as of the Task 5/6 verification pass.

## 1. Separate authentication, end to end

Staff and portal customers are different kinds of principal, authenticated
by different, non-interchangeable schemes:

| | Staff | Portal customer |
|---|---|---|
| Identity | `accounts.User` row | `parties.Party` row |
| Token | JWT (SimpleJWT), `Authorization: Bearer <token>` | Signed token (`django.core.signing`), `Authorization: Portal <token>` |
| Sets on request | `request.user` | `request.party` (never `request.user`) |
| DRF auth class | `JWTAuthentication` / `SessionAuthentication` (defaults) | `PortalTokenAuthentication` only |
| Lifetime | Access token minutes, refresh token days (both env-configurable), rotated + blacklisted on refresh | 7 days, or immediately if `Party.portal_access_revoked_at` is set after issue (see §4) |

Because a portal token never sets `request.user`, it can never satisfy
`IsAuthenticated`/`HasPerm` on a staff endpoint — there is no user for
those checks to inspect. Because a staff JWT is a completely different
token format read by a completely different `authentication_classes`
list, `PortalTokenAuthentication.authenticate()` simply returns `None`
for it (no `Portal <token>` prefix) and `IsPortalCustomer` then denies
(`request.party` was never set). Every `Portal*View` that serves real
customer data (`PortalMeView`, `PortalInvoicesView`, `PortalRepairsView`,
`PortalRentalsView`, `PortalWarrantiesView`, `PortalFeedbackView`,
`PortalLocationView`) sets exactly
`authentication_classes = [PortalTokenAuthentication]` and
`permission_classes = [IsPortalCustomer]` — audited directly, not assumed.

The two pre-login endpoints (`PortalInviteStatusView`, `PortalVerifyView`)
are `AllowAny` with `authentication_classes = []`, deliberately emptied
rather than left to DRF's default chain — otherwise `SessionAuthentication`
would still run and enforce CSRF using a staff member's leftover admin
session cookie, on a page their portal customer never needed a CSRF
token for.

## 2. Separate frontend entry point

`PortalApp.jsx` is its own React tree, lazy-loaded only when the URL
matches `/portal/...`. It never mounts the staff `Shell`/`App.jsx`
component tree, so there is no code path where a staff session and a
portal session share client-side state.

## 3. API-only contract, no shared session

The portal talks to Django exclusively through `/api/portal/*` REST
endpoints (`portal/urls.py`). No server-rendered pages, no session
cookie shared between the two — the portal's own auth (§1) is
completely stateless, so there is nothing to share in the first place.

## 4. Revocation (added this pass)

Signed tokens can't be individually invalidated the way a database
session can — there's no row to delete. `Party.portal_access_revoked_at`
closes that gap: `issue_portal_token` stamps the token with its own
issue time, and `resolve_portal_token` rejects any token issued at or
before the party's revocation timestamp, regardless of how much of its
7-day natural life is left. Staff can trigger this via
`POST /parties/{id}/revoke-portal-access/` (gated by `parties.manage`,
same as every other party action).

## 5. Data isolation

Every `Portal*View` filters its queryset by `request.party` — never by
an ID taken from the request body or query string — so a valid portal
token can only ever return that one customer's own invoices, repairs,
rentals, warranties and feedback. Verified by reading each view
directly, not inferred from the auth layer alone.

## 6. Domain separation readiness

`PUBLIC_FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS`
are all environment-driven (`DJANGO_CORS_ALLOWED_ORIGINS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`), with `CORS_ALLOWED_ORIGINS` defaulting to
the single local Vite origin only for developer convenience. Since the
portal never uses cookies (§1), `SESSION_COOKIE_SAMESITE=Lax` — which
would block a cross-site cookie — never comes into play for portal
traffic. Moving the portal to its own subdomain or domain later is a
pure environment-variable change: add the new origin to the two lists
above and point `PUBLIC_FRONTEND_URL` at it. No application code change
is required.

## Verification pass log

- Sep 29, 2026 — full read of `portal/views.py`, `portal/auth.py`,
  `crmbook_backend/settings.py` (REST_FRAMEWORK, CORS, CSRF, session
  cookie sections). Found and fixed: missing `authentication_classes = []`
  on the two pre-login views (CSRF-via-session-cookie regression); no
  portal token revocation mechanism (added `portal_access_revoked_at`);
  no throttle on the OTP verify endpoint (added `OTPVerifyThrottle`).
  See the Task 6 checklist in the project's build pipeline doc for the
  full security audit this note feeds into.
