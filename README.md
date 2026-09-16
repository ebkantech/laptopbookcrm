# CRMBook -- Django + React

A laptop hardware business CRM: shared inventory across shops and online
channels, sales invoicing with payment links, rentals with churn scoring,
a repairs & service ticket lifecycle, secure customer approvals, cash/bank books, object-based role
access, and WhatsApp/email touchpoints throughout.

- **Backend**: Django + Django REST Framework, JWT auth, SQLite by default.
- **Frontend**: React (Vite), fetching everything live from the API. No
  mock arrays left in the app -- every page loads from `/api/...`.

This was converted from a single-file React prototype. The backend has
been migrated, seeded, and exercised end-to-end (login, every list
endpoint, ticket-stage advance, invoice creation with real stock
decrement, and a role-permission denial) before being handed over.

## 1. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate 
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo                   # loads the full demo dataset
python manage.py createsuperuser  # optional -- seed_demo already makes
                                   # aman.kapoor a superuser
python manage.py runserver
```

API root: `http://127.0.0.1:8000/api/`
Admin: `http://127.0.0.1:8000/admin/`

Seeded logins (password for all: `crmbook123`):

| Username       | Role            |
|----------------|-----------------|
| aman.kapoor    | Owner (superuser) |
| ritu.sharma    | Accountant      |
| vikram.sethi   | Store Manager   |
| naina.joshi    | Sales Executive |
| deepa.iyer     | Auditor (read-only) |

Sign in as different users to see the same screens behave differently --
that's the object-based permission model (`accounts.Permission` /
`accounts.Role`) driving `HasPerm` on every ViewSet.

## 2. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env    # points VITE_API_URL at the backend
npm run dev
```

Open `http://localhost:5173`, sign in with any seeded user above.

## 3. Local PostgreSQL (recommended before deployment)

SQLite remains the zero-setup default. To test the same database engine that
will run in staging/production, install PostgreSQL 17 or newer locally, create a fresh
`crmbook_dev` database and copy `backend/.env.example` to `backend/.env`.
The `.env` file is ignored by Git; never commit a password.

```env
POSTGRES_DB=crmbook_dev
POSTGRES_USER=crmbook_app
POSTGRES_PASSWORD=use-a-unique-local-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_SSLMODE=
POSTGRES_CONN_HEALTH_CHECKS=False
```

Then, from `backend/`, install dependencies and build a *fresh* demo database:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py check --database default
python manage.py test
```

Django creates a temporary test database when running `manage.py test`. For
this local-only setup, grant the local `crmbook_app` role `CREATEDB` once using
the `postgres` administrator account. Do **not** grant `CREATEDB` to the
application role used in staging or production.

The existing SQLite file contains demo/test data, so do not copy it into the
local PostgreSQL database. For a future real-data cutover, use a separately
reviewed backup/export/import plan and a maintenance window.

## 4. What's live vs. what's still a stub

**Fully wired to the database** (not mock data): inventory & shared
stock, parties & their WhatsApp/email thread, invoices (create decrements
real stock, settle marks paid), single/bulk rentals with physical asset tracking,
24-hour approval links and audit history, repair tickets (full lifecycle:
create -> advance stage -> settle & auto-generate a repair invoice, with
notifications logged at each step), combined bulk-repair approval, cash book, bank book + reconciliation,
roles & permissions matrix, broadcast campaigns, inbound WhatsApp orders.

**Still demo data on the frontend**: the Dashboard's "Income trend"
line chart. There isn't enough transaction history yet to aggregate a
real multi-month series, so `dashboard/views.py` returns the KPIs, the
low-stock list, and the churn leaderboard from real data, and the chart
series stays as a labeled demo placeholder in `Dashboard.jsx` until
there's enough invoice history to chart for real -- swap it for a new
`/api/dashboard/trends/` endpoint once that data exists.

**Not implemented** (kept out of scope for this pass): payment gateway
webhook (invoice `settle` is a manual action, not a Razorpay callback),
outbound WhatsApp/email are logged, not actually sent (swap
`Notification.objects.create(...)` calls for a real provider SDK when
ready), and the "Quotation assistant" chat screen from the prototype
wasn't ported -- it can be rebuilt against `/api/parties/`,
`/api/products/`, and `/api/whatsapp-orders/`.

## 5. Project layout

```
backend/
  crmbook_backend/     settings, root urls
  accounts/            custom User, Role, Permission, JWT-backed auth
  catalog/              Product, Variant, Stock, Part, Service
  parties/              Party, Message (WhatsApp/email thread)
  sales/                Invoice, InvoiceItem
  rentals/               Rental (+ churn_score property)
  repairs/               RepairTicket, RepairInvoice, Notification
  accounting/            CashEntry, BankAccount, BankEntry
  broadcast/              Campaign, WhatsAppOrder
  dashboard/              aggregated summary endpoint

frontend/
  src/lib/               theme tokens, api client (JWT + auto-refresh)
  src/context/            SessionContext (current user + can())
  src/components/         shared UI atoms
  src/pages/               one file per module, matching the nav
```

## 6. Before production

- Swap `SECRET_KEY` and set `DEBUG=False`, real `ALLOWED_HOSTS`.
- Move off SQLite to Postgres for concurrent writes (stock decrement
  currently uses an atomic `F()` update, which is safe on any backend,
  but SQLite's write-locking will bottleneck under real concurrent load).
- Tailwind and Bootstrap are bundled locally by Vite; keep `npm ci && npm run build`
  in the production build pipeline. Public approval routes are lazy-loaded and
  use a no-referrer policy.
- Wire the WhatsApp Business API and an email provider behind the
  `Notification` / `Message` creation points.
- Wire a payment gateway webhook to call `Invoice.settle` automatically
  instead of the manual "Mark settled" button.

## 7. Rental and repair approval workflow

- Rental type is derived from physical line count: one asset is `single`, two
  or more assets are `bulk`; staff cannot manually create a contradictory type.
- A rental approval freezes a 24-hour snapshot containing device identity,
  duration, terms and monthly prices. Only a SHA-256 token hash is stored.
- Admin/Super Admin approval requires a reason. Cancelling or closing an
  agreement releases its assets and writes an audit event; agreements are not
  hard-deleted.
- A bulk repair order retains one ticket and final estimate per physical device.
  Once every device estimate is finalized, one combined link displays all work,
  device totals and the grand total. The decision is recorded against every
  child estimate, so existing stage guards continue to apply.
- Approval links are provider-independent: copy the HTTPS URL into WhatsApp or
  email. WhatsApp Cloud API is not required for this workflow.

After pulling approval-related changes, run:

```bash
cd backend
python manage.py migrate
python manage.py test

cd ../frontend
npm ci
npm run build
```
