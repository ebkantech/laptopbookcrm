# VantageCRM — security review and hardening (Nov 2026)

What was checked, what was found, what the code now does, and the steps that
only the owner can carry out (hosting settings, Git history, password resets).

Severity: 🔴 urgent · 🟠 medium · 🟡 low.

---

## 1. Findings and status

| # | Finding | Sev. | Status |
|---|---------|------|--------|
| 1 | Database dump `crmbook.sql` (6 staff password hashes, customers, invoices, messages), `backend/users_export.json` (6 password hashes), `backend/rental-handover-backup.zip` (37 customer device photos) committed to Git. `backend/.env.example` held a real-looking database password (since commit `c5bd0ce`). | 🔴 | **Owner action** — section 3. `.env.example` now has a placeholder. |
| 2 | Login rate limit bypassable: a client could send its own `X-Forwarded-For` on each request and never be limited (verified). Same for portal OTP, password-setup and approval-link limits. | 🔴 | **Fixed** — `NUM_PROXIES`; only the address the hosting proxy adds is trusted. |
| 3 | If `DJANGO_SECRET_KEY` was missing in production, Django started on the public development key, so anyone could forge login tokens. | 🔴 | **Fixed** — production refuses to start without a real key. |
| 4 | Django admin login (`/admin/`) had no rate limit (verified: 8 rapid wrong passwords, none blocked). | 🟠 | **Fixed** — same per-address limit and account lockout as the API login; can be moved or switched off. |
| 5 | Rate limits counted in per-process memory: multiplied by the number of workers, reset on every deploy. | 🟠 | **Fixed** — shared database cache (table created by migration). |
| 6 | Staff and portal tokens live in `localStorage`; the frontend sent no security headers (no CSP), so one injected script could steal a 7-day session. | 🟠 | **Mitigated** — `frontend/public/_headers` (CSP, frame, HSTS…). Moving the refresh token into an HttpOnly cookie is a later step. |
| 7 | `cryptography` pinned below 46 — 13 published advisories (pip-audit). | 🟠 | **Fixed** — `>=50.0.2,<51`. |
| 8 | Permission check allowed any action missing from a view's permission map (none exposed today, but fail-open). Also `POST /api/stock-serials/` gave a 500. | 🟠 | **Fixed** — unmapped actions are refused and logged; serial endpoint limited. |
| 9 | HSTS only 1 hour by default. | 🟡 | `.env.example` now suggests 1 year — set it on Render. |
| 10 | Sign-ins were not audited; no protection against slow guessing of one account from many addresses. | 🟡 | **Fixed** — every sign-in recorded (`LoginAttempt`), 10 failures in 15 min lock that username for the rest of the window. |
| 11 | A password change left access tokens valid up to 60 min; sessions could be kept alive forever by refreshing. | 🟡 | **Fixed** — tokens die on password change; one sign-in lasts at most 30 days. |
| 12 | Token blacklist table only grows. | 🟡 | **Owner action** — schedule `flushexpiredtokens` (section 2). |
| 13 | Database TLS to Supabase not enforced. | 🟡 | **Fixed** — `sslmode=require` automatically for a Supabase host (or set `POSTGRES_SSLMODE`). |

Already in place and confirmed: DEBUG off by default; allowed hosts from env;
HTTPS redirect, secure cookies, no-sniff, frame-deny; explicit CORS / CSRF
allow-lists (no wildcard); password policy (10+ chars, not common / numeric /
like the name); one-time 24-hour setup links; JWT rotation + blacklist on
logout, deactivation and password change; per-permission access + store
isolation + no privilege escalation; staff activity log (personal data masked),
permission-denial log, admin-action log; public approval links store only a
hash of the token, are rate-limited and sent `no-store` / `no-referrer`;
Razorpay / WhatsApp webhooks verify signatures; uploads type-checked and only
streamed to signed-in staff; `npm audit` clean; no `dangerouslySetInnerHTML`.

---

## 2. Settings to set on the hosts

### Render (backend environment)

| Variable | Value | Why |
|----------|-------|-----|
| `DJANGO_SECRET_KEY` | 50+ random characters — `python -c "import secrets; print(secrets.token_urlsafe(64))"` | **Required.** The app will not start without it. Never reuse the example. |
| `DJANGO_DEBUG` | *not set* (or `False`) | |
| `DJANGO_ALLOWED_HOSTS` | your API domain(s) only | |
| `DJANGO_CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | your frontend origin(s) only, `https://…` | |
| `DJANGO_NUM_PROXIES` | `1` (Render). `2` if the API domain is also proxied by Cloudflare (orange cloud). | Rate limits read the true client address. |
| `DJANGO_HSTS_SECONDS` | `31536000` | Browsers only ever use HTTPS. |
| `POSTGRES_SSLMODE` | `require` | Encrypted database connection. |
| `DJANGO_ADMIN_ENABLED` | `False` if nobody uses `/admin/`; otherwise keep and set `DJANGO_ADMIN_URL` to something not guessable, e.g. `staff-console-7f3k/` | |
| optional | `LOGIN_MAX_FAILURES=10`, `LOGIN_FAILURE_WINDOW_MINUTES=15`, `JWT_MAX_SESSION_DAYS=30`, `JWT_ACCESS_MINUTES=60`, `JWT_REFRESH_DAYS=7` | Tuning. |

Deploy command must run `python manage.py migrate` (creates the
`django_cache` table and the login audit table).

**Scheduled job (Render cron, weekly):** `python manage.py flushexpiredtokens`

**Expect once after this deploy:** everyone is signed out and signs in again
(tokens now carry a password fingerprint).

### Cloudflare (frontend)

`frontend/public/_headers` is copied into `dist/` by `npm run build` and applied
by Cloudflare Pages automatically. In it, replace `connect-src 'self' https:`
with your exact API origin, e.g. `connect-src 'self' https://your-api.onrender.com`.
Check in the browser (F12 → Network → the page → Response headers) that
`content-security-policy` is present.

### Local development

`backend/.env` must contain `DJANGO_DEBUG=True` (or a real
`DJANGO_SECRET_KEY`), otherwise `manage.py` stops with
"DJANGO_SECRET_KEY must be set…". Locally you may also set
`DJANGO_NUM_PROXIES=0` and `DJANGO_CACHE=locmem`.

---

## 3. Remove the leaked files from Git (owner)

Do this from a fresh folder, not the working copy. It rewrites history, so
**tell everyone who has cloned the repo** (including your colleague) to delete
their copy and clone again afterwards.

```powershell
# 0. Install the tool once
pip install git-filter-repo

# 1. Fresh mirror copy
cd C:\Users\lenovo\Desktop
git clone --mirror https://github.com/ebkantech/laptopbookcrm.git laptopbookcrm-clean.git
cd laptopbookcrm-clean.git

# 2. Remove the files from every commit
git filter-repo --invert-paths `
  --path crmbook.sql `
  --path backend/users_export.json `
  --path backend/rental-handover-backup.zip `
  --path backend/compare_db.py `
  --path frontend/frontend-dist.zip

# 3. Remove the old database password from every version of .env.example.
#    Create replacements.txt in this folder containing ONE line:
#        <the old password>==>REMOVED
#    (type it yourself -- never paste it into chat), then:
git filter-repo --replace-text replacements.txt
del replacements.txt

# 4. Push the cleaned history
git remote add origin https://github.com/ebkantech/laptopbookcrm.git
git push --force --all
git push --force --tags
```

Then:

1. In your normal working folder: `git fetch origin` and `git reset --hard origin/main`
   (after saving any uncommitted work), or simply clone again.
2. Keep the removed files out for good — they are already in `.gitignore`;
   store backups outside the project folder.
3. If the repository was **ever public** or shared with anyone outside the team:
   check GitHub for forks, ask GitHub Support to purge cached views, and treat the
   customer data as exposed — check with your adviser whether the Digital Personal
   Data Protection Act requires notifying anyone.

### Rotate (whether or not it was public)

- Reset the password of every staff account that existed when the dump was made
  (Settings → Staff management → Reset password).
- Change the local PostgreSQL password, and the Supabase database password if it
  was ever the same; update `POSTGRES_PASSWORD` wherever it is set.
- If production ever ran without its own `DJANGO_SECRET_KEY`, set a new one
  (signs everyone out).
- `.cpanel.yml` copies all of `backend/` to the server — delete any copies of the
  files above there too.

---

## 4. What changed in the code

| Area | Files |
|------|-------|
| Secret-key guard, `NUM_PROXIES`, shared cache, admin toggle, JWT revoke + session cap settings, lockout settings, Supabase TLS | `backend/crmbook_backend/settings.py`, `backend/crmbook_backend/urls.py` |
| Login audit, per-account lockout, session cap, admin-login limit | `backend/accounts/auth.py`, `backend/accounts/middleware.py`, `backend/accounts/models.py` (`LoginAttempt`), `backend/accounts/admin.py`, `backend/accounts/apps.py`, `backend/accounts/views.py`, migration `accounts/0018_login_audit_cache.py` |
| Fail-closed permissions | `backend/accounts/permissions.py`, explicit entries in `accounts/views.py`, `catalog/views.py`, `rentals/views.py` |
| Dependencies / examples | `backend/requirements.txt`, `backend/.env.example` |
| Frontend headers | `frontend/public/_headers`; print windows no longer use inline scripts (`pages/Inventory.jsx`, `components/serials/serialLabels.js`) |
| Tests | `backend/accounts/test_security_hardening.py` |

Sign-in audit: Django admin → Accounts → Login attempts (read-only). Locked
accounts are also written to the server log (`accounts.security`).

Later improvements worth doing: refresh token in an HttpOnly cookie instead of
`localStorage`; a staff screen for the login audit; optional two-step sign-in
for Owner / Admin accounts.
