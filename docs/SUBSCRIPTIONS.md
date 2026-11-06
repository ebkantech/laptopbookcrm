# Subscriptions

Each client has their own installation with one plan. The modules, their
dependencies and the blocking rules are in `backend/subscriptions/`.

## Start or renew a plan

    python manage.py activate_subscription <starter|service|rental|full> <1|3|6|12>

Prices and package contents can be changed in Django admin. With no plan set,
nothing is limited.

## States

- **Active:** normal use. Reminders go to Super Admins 7, 3 and 1 days before the end.
- **Grace:** 7 days after the end. Everything works, with a warning.
- **Read-only:** view and export only. Background jobs stop creating records.

Data is never deleted, and a module outside the plan is refused, not uninstalled.

## Background jobs

Install Redis, then run these alongside Django:

    celery -A crmbook_backend worker -l info    (Windows: add --pool=solo)
    celery -A crmbook_backend beat -l info

Beat runs the AI-Staff index at 02:00, the subscription check at 08:00, rent
invoices at 09:00 and warranty reminders at 09:30, India time.
