# VantageCRM 26X — Roles & Permissions

This is the single source of truth for the RBAC model. It must be kept in
sync with `backend/catalog/management/commands/seed_demo.py` (the `PERMS`
and `ROLES` dicts) and with every ViewSet's `required_perm(s)` — if you
change one, update the other two and this file in the same change.

## How it works

- Every permission is a `codename` (e.g. `parties.manage`) stored as an
  `accounts.models.Permission` row.
- Every staff `User` has one `Role` (`accounts.models.Role`), which holds a
  set of `Permission`s.
- `user.has_perm_code("some.codename")` is the single check used
  everywhere — a superuser (the Owner account) always passes regardless of
  role.
- On each ViewSet, `accounts.permissions.HasPerm` reads either
  `required_perm = "x.y"` (same check for every action) or
  `required_perms = {"list": "x.view", "create": "x.manage", ...}`
  (per DRF action, keyed by `view.action`). **An action left out of a
  `required_perms` dict is open to any authenticated staff member** — when
  adding a new `@action` to a ViewSet that already has `required_perms`,
  you must add an explicit entry for it, or it silently has no permission
  check at all.
- `accounts.permissions.IsStaffAccount` (no permission check, just "is this
  a real staff account and not a portal customer") is only appropriate for
  endpoints with no sensitive data and no role distinction — currently
  that's the read-only catalogue lookups (`StockPointViewSet`,
  `PartViewSet`, `ServiceViewSet`) and the shared `DashboardView` /
  `DashboardLayoutView`, which narrow their own output per role via
  `dashboard.layouts.visible_sections()`.

## Roles

| Slug | Label | Notes |
|---|---|---|
| `owner` | Owner / Super Admin | `is_superuser=True` — bypasses all permission checks outright, regardless of what's in its role's permission set |
| `manager` | Admin | Second-in-command; everything except being the literal superuser account |
| `sales` | Sales Staff | Narrowed to sales-floor + customer-facing work only |
| `repair_staff` | Repair Staff | New role; repairs + warranty only |
| `accountant` | Accounts | Books, invoices, reports |
| `auditor` | Auditor — read only | Full read-only visibility, no write access anywhere |

## Permission matrix

✅ = granted · — = not granted (Owner has every permission via superuser
bypass, shown here for reference as if it were role-based too, since
`ROLES["owner"]` does list every code)

| Permission | Description | Owner | Admin | Sales Staff | Repair Staff | Accounts | Auditor |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `cashbook.view` | View the cash book | ✅ | ✅ | — | — | ✅ | ✅ |
| `cashbook.edit` | Add or edit cash entries | ✅ | ✅ | — | — | ✅ | — |
| `bankbook.view` | View the bank book | ✅ | ✅ | — | — | ✅ | ✅ |
| `bankbook.edit` | Add or edit bank entries | ✅ | ✅ | — | — | ✅ | — |
| `bankbook.reconcile` | Mark bank entries reconciled | ✅ | ✅ | — | — | ✅ | — |
| `invoices.view` | View invoices | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| `invoices.create` | Create invoices & payment links | ✅ | ✅ | ✅ | — | — | — |
| `invoices.settle` | Mark invoices settled | ✅ | ✅ | ✅ | — | ✅ | — |
| `payments.send_link` | Send UPI payment links to customers | ✅ | ✅ | ✅ | — | ✅ | — |
| `inventory.edit` | Edit stock and product records | ✅ | ✅ | — | — | — | — |
| `rentals.view` | View rental assets | ✅ | ✅ | ✅ | — | — | ✅ |
| `rentals.manage` | Manage rental accounts | ✅ | ✅ | ✅ | — | — | — |
| `rentals.approve` | Approve rental agreements on behalf of customers | ✅ | ✅ | — | — | — | — |
| `repairs.view` | View repair tickets | ✅ | ✅ | — | ✅ | — | ✅ |
| `repairs.manage` | Create tickets, update stages, settle repair bills | ✅ | ✅ | — | ✅ | — | — |
| `repairs.approve` | Approve repair estimates on behalf of customers | ✅ | ✅ | — | — | — | — |
| `broadcast.send` | Send WhatsApp / email campaigns | ✅ | ✅ | — | — | — | — |
| `warranty.manage` | Register and edit customer warranties | ✅ | ✅ | — | ✅ | — | — |
| `portal.manage` | Send customer portal access links | ✅ | ✅ | — | — | — | — |
| `roles.manage` | Change roles and permissions | ✅ | ✅ | — | — | — | — |
| `reports.export` | Export accounting reports | ✅ | ✅ | — | — | ✅ | ✅ |
| `reports.profit_loss` | View store Profit & Loss (Admins only; limited to their stores) — see note below | ✅ | ✅ | — | — | — | — |
| `expenses.manage` | Record and manage expenses and their attachments (Admins and Accounts only; limited to their stores) — see note below | ✅ | ✅ | — | — | ✅ | — |
| `parties.view` | View the customer directory and details | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `parties.manage` | Create/edit customer records, message customers, manage portal access | ✅ | ✅ | ✅ | — | — | — |
| `orders.manage` | View and respond to inbound WhatsApp orders | ✅ | ✅ | ✅ | — | — | — |

## Where each permission is enforced

| Permission(s) | ViewSet / View | File |
|---|---|---|
| `cashbook.view` / `cashbook.edit` | `CashEntryViewSet` | `backend/accounting/views.py` |
| `bankbook.view` | `BankAccountViewSet` | `backend/accounting/views.py` |
| `bankbook.view` / `bankbook.edit` / `bankbook.reconcile` | `BankEntryViewSet` | `backend/accounting/views.py` |
| `invoices.view` / `invoices.create` / `invoices.settle` | `InvoiceViewSet` | `backend/sales/views.py` |
| `payments.send_link` | `InvoiceViewSet.upi_check` / `send_upi_link` / `refresh_payment` (also hard-refused for the `repair_staff` role, whatever its permissions) | `backend/sales/views.py` |
| `inventory.edit` | `ProductViewSet`, `AddStockView` | `backend/catalog/views.py` |
| `rentals.view` / `rentals.manage` / `rentals.approve` | `RentalViewSet`, `RentalAssetViewSet` | `backend/rentals/views.py` |
| `rentals.manage` | `RentalIssueViewSet` (assign/resolve) | `backend/rentals/views.py` |
| `repairs.view` / `repairs.manage` / `repairs.approve` | `RepairTicketViewSet`, `RepairOrderViewSet` | `backend/repairs/views.py` |
| `repairs.view` | `RepairInvoiceViewSet` | `backend/repairs/views.py` |
| `broadcast.send` | `CampaignViewSet` | `backend/broadcast/views.py` |
| `orders.manage` | `WhatsAppOrderViewSet` | `backend/broadcast/views.py` |
| `warranty.manage` | `WarrantyViewSet` | `backend/warranty/views.py` |
| `portal.manage` | `PortalInviteViewSet`, `PortalAccessLogListView` | `backend/portal/views.py` |
| `parties.view` / `parties.manage` | `PartyViewSet` | `backend/parties/views.py` |
| `reports.profit_loss` | `ProfitLossView`, `ProfitLossTransactionsView`, `ProfitLossStoresView` via `reports.profit_loss.CanViewProfitLoss` | `backend/reports/views.py`, `backend/reports/profit_loss.py` |
| `expenses.manage` | `ExpenseViewSet`, `ExpenseCategoryViewSet`, `ExpenseAttachmentFileView` via `accounting.expense_views.CanManageExpenses` | `backend/accounting/expense_views.py`, `backend/accounting/expenses.py` |
| `roles.manage` | *(seeded, not yet enforced anywhere — reserved for the future admin-facing role-assignment screen)* | — |
| — (open to any staff) | `StockPointViewSet`, `PartViewSet`, `ServiceViewSet`, `DashboardView` | `backend/catalog/views.py`, `backend/dashboard/views.py` |
| — (read-only for any staff, editing is Django-admin-only) | `PermissionViewSet`, `RoleViewSet`, `UserViewSet` | `backend/accounts/views.py` |

### Store-wise Profit & Loss (`reports.profit_loss`)

Holding the permission is necessary but not sufficient. Access requires
**Superuser**, or an **Admin-tier** account (`accounts.staff.is_staff_admin`:
the Owner role or `roles.manage`) whose role **also** holds
`reports.profit_loss`. Any other role given the permission (e.g. Accounts) is
still refused, and `is_staff` plays no part. Stores come from
`accounts.store_scope.StoreScope`: Superuser / Owner reach every store and
get the store comparison and consolidated total; a store-assigned Admin
reaches only their own store (any other `store` id is a 403); an unassigned
Admin reaches none. Every refusal is a 403, logged in `PermissionDeniedLog`.
Migration `accounts/0010_profit_loss_permission` grants it to the `owner`
and `manager` (Admin) roles; remove it from a role to withdraw access.

### Expenses (`expenses.manage`)

Accounting → Expenses: list, bulk entry, details, edit, payments, cancel,
attachment upload / preview / download. Access requires **Superuser**, or an
**Admin-tier** account (Owner role or `roles.manage`) or an **Accounts**
account (role slug `accountant`) whose role **also** holds `expenses.manage`.
Any other role holding it (e.g. Sales Staff) is still refused with 403, and
`is_staff` plays no part. Records go through `StoreScope`: store-assigned
Admin / Accounts users reach only their store's expenses and attachments
(another store's id is a 404, recording one for another store is refused);
shared / head-office expenses (no store) are reachable only by an account
that sees every store. Migration `accounts/0011_expenses_permission` grants
it to the `owner`, `manager` and `accountant` roles.

## Known gaps / deliberately deferred

- **Dashboard is not yet split by role** — every staff member sees the same
  `DashboardView` output today. Splitting it into role-scoped widgets is
  Task 4 of the Phase 2 pipeline, not part of this RBAC pass.
- **`roles.manage` is seeded but not enforced anywhere yet** — there is no
  in-app screen for assigning roles to users. Today that's done through
  Django admin (`/admin/`), which is Owner/superuser-only by default. If an
  in-app role-assignment screen is built later, it should require
  `roles.manage`.
- **Frontend nav is not permission-filtered yet** — the sidebar currently
  shows every section to every logged-in user regardless of role; the API
  correctly returns 403 for anything they're not allowed to touch, but the
  link itself isn't hidden. Tracked as the next item after this document.

## Demo accounts

All seeded via `python manage.py seed_demo`, password `crmbook123` for
everyone.

| Username | Role |
|---|---|
| `aman.kapoor` | Owner / Super Admin (`is_superuser=True`) |
| `vikram.sethi` | Admin |
| `naina.joshi` | Sales Staff |
| `suresh.rana` | Repair Staff |
| `ritu.sharma` | Accounts |
| `deepa.iyer` | Auditor — read only |
