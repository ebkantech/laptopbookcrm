"""
Active / Inactive shops and channels (catalog.StockPoint.is_active).

An inactive stock point takes no NEW business: no new sale or rent
invoice, repair ticket or repair order, no stock added to or taken out of
it, no rental unit issued from or returned into its stock, and no staff
newly assigned to it. Everything already recorded there -- invoices,
payments, refunds, repairs, rentals, stock rows, staff links -- stays
exactly as it is and keeps its normal follow-up actions (settle, refund,
cancel, complete, return, correct).

Each workflow that creates or re-points a record calls require_active()
for the stock point it is about to use, so the rule holds for direct API
calls, not just the UI. An unchanged stock point on an existing record is
never refused (see `current`).

Who may see the status and change it: Superuser, the Owner / Super Admin
and staff administrators (roles.manage) -- accounts.staff.is_staff_admin,
the same rule that governs staff management. Store-assigned administrators
reach only their own store, through the usual StoreScope.
"""
from rest_framework.exceptions import ValidationError

INACTIVE_DETAIL = (
    "{name} is inactive, so new {what} can't be recorded there. "
    "Choose an active shop or channel, or ask an administrator to reactivate it."
)


def can_manage_status(user):
    from accounts.staff import is_staff_admin
    return bool(user and user.is_authenticated and is_staff_admin(user))


def require_active(stock_point, what="operations", field="stock_point", current=None):
    """
    Refuse `stock_point` for a new operation if it is inactive. `current`
    is the stock point (or its id) the record already has: keeping it is
    an update to existing history, not a new operation, so it's allowed.
    """
    if stock_point is None or stock_point.is_active:
        return
    current_id = getattr(current, "pk", current)
    if current_id is not None and current_id == stock_point.pk:
        return
    raise ValidationError({field: INACTIVE_DETAIL.format(name=stock_point.name, what=what)})
