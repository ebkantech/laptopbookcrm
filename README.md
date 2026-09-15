# CRMBook -- Django + React

A laptop hardware business CRM: shared inventory across shops and online
channels, sales invoicing with payment links, rentals with churn scoring,
a repairs & service ticket lifecycle, cash/bank books, object-based role
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

## 3. What's live vs. what's still a stub

**Fully wired to the database** (not mock data): inventory & shared
stock, parties & their WhatsApp/email thread, invoices (create decrements
real stock, settle marks paid), rentals (churn score computed server-side
in `rentals.models.Rental.churn_score`), repair tickets (full lifecycle:
create -> advance stage -> settle & auto-generate a repair invoice, with
notifications logged at each step), cash book, bank book + reconciliation,
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

## 4. Project layout

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

## 5. Before production

- Swap `SECRET_KEY` and set `DEBUG=False`, real `ALLOWED_HOSTS`.
- Move off SQLite to Postgres for concurrent writes (stock decrement
  currently uses an atomic `F()` update, which is safe on any backend,
  but SQLite's write-locking will bottleneck under real concurrent load).
- Replace the Tailwind Play CDN `<script>` in `index.html` with a real
  Tailwind build (`npm install -D tailwindcss postcss autoprefixer`) --
  the CDN build is fine for development but not meant for production.
- Wire the WhatsApp Business API and an email provider behind the
  `Notification` / `Message` creation points.
- Wire a payment gateway webhook to call `Invoice.settle` automatically
  instead of the manual "Mark settled" button.
