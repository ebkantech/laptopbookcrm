# VantageCRM 26X — Notifications (WhatsApp & Email)

How outbound customer communication works, and how to turn on real
sending once you have a Meta WhatsApp Business account and an email
provider. Keep this in sync with `backend/crmbook_backend/notify.py`
(the actual code) whenever either changes.

## How it works today

Every place in the app that "sends" something to a customer goes
through exactly two functions, both in `backend/crmbook_backend/notify.py`:

- `send_whatsapp(to, body)`
- `send_email(to, subject, body)`

Nothing else in the codebase talks to a provider directly. That's
deliberate: switching providers later is a change in that one file (or
just an environment variable), not a hunt through every view that sends
something.

**Right now, both are test/simulated backends — nothing leaves your
machine:**
- WhatsApp: the `console` provider (default) just logs the message to
  the `runserver` terminal and marks it `simulated`.
- Email: Django's built-in **console email backend** (`EMAIL_BACKEND`
  in `settings.py`) prints the full email to the `runserver` terminal.

Every send is **fail-soft** — if a send fails, it's logged and the
request still succeeds. Creating a repair ticket must never 500 just
because a notification failed to go out. The `Message` (parties app)
and `Notification` (repairs app) database rows are the durable record
of "this was communicated to the customer"; `notify.py`'s functions are
the (currently simulated) delivery attempt on top of that record.

## Turning on real WhatsApp sending (Meta Cloud API)

You need a Meta Business Manager account with the WhatsApp product
added, a verified phone number, and a **permanent** System User access
token (not the 24-hour temporary one from the quickstart). Once you
have those:

1. Set these in `backend/.env`:
   ```
   WHATSAPP_PROVIDER=meta_cloud
   WHATSAPP_PHONE_NUMBER_ID=<from the Meta developer console>
   WHATSAPP_ACCESS_TOKEN=<permanent System User token>
   ```
2. That's it — every call site already routes through `send_whatsapp()`.

**One real constraint to plan for before flipping this on**: outside a
24-hour window since the customer last messaged your business number,
Meta requires a pre-approved message *template* rather than free-form
text like `send_whatsapp` currently sends. Which messages need a
template (portal invites? repair updates?) and getting them approved by
Meta is a product decision to make at that point, not before — the
`_send_whatsapp_meta_cloud` function in `notify.py` has a note on this.

## Turning on real email sending

Change `DJANGO_EMAIL_BACKEND` in `backend/.env` to a real SMTP backend,
e.g.:
```
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yourprovider.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=True
DJANGO_DEFAULT_FROM_EMAIL=support@vantagecomputers.example
```
No code changes needed — `send_email()` already goes through Django's
standard `send_mail()`, which respects whatever `EMAIL_BACKEND` is set.

## Role → channel mapping

| Trigger | Channel(s) | Gated by | Where |
|---|---|---|---|
| Portal invite / reset link | WhatsApp + Email | `portal.manage` | `portal/views.py: PortalInviteViewSet`, `parties/views.py: _issue_portal_invite` |
| Ad-hoc customer message | WhatsApp or Email (staff picks) | `parties.manage` | `parties/views.py: PartyViewSet.send_message` |
| Repair ticket created / order created | WhatsApp + Email | side-effect of `repairs.manage` | `repairs/views.py: RepairTicketViewSet.perform_create`, `RepairOrderViewSet.create` |
| Repair stage advances (`advance`, `set-stage`) | WhatsApp + Email | side-effect of `repairs.manage` | `repairs/views.py` |
| Repair settled (invoice generated) | WhatsApp + Email | side-effect of `repairs.manage` | `repairs/views.py: RepairTicketViewSet.settle` |
| Repair reopened for a follow-up visit | WhatsApp + Email | side-effect of `repairs.manage` | `repairs/views.py: RepairTicketViewSet.reopen` |
| Warranty registered | Email | side-effect of `warranty.manage` | `warranty/views.py` |
| Repair approval link | WhatsApp — real `wa.me` click-to-chat link, staff clicks to send | `repairs.manage` | `repairs/services.py: issue_approval_link` — already fully working today, real WhatsApp, no `notify.py` involved |
| Rental approval link | none yet — staff must manually share the raw URL | `rentals.manage` | `rentals/services.py: issue_approval_link` — **not wired to any channel**, only returns the bare approval URL |
| Marketing campaigns | simulated only | `broadcast.send` | `broadcast/views.py: CampaignViewSet` — **deliberately not wired**, see below |

## Staff alerts (internal, role-based)

Separate from everything above, which is all customer-facing.
`accounts.models.NotificationRule` + `crmbook_backend.notify.notify_staff()`
let a business event alert whichever **staff roles** care about it, by
email and/or WhatsApp -- configured on **Settings > Staff alerts** (gated
by `roles.manage`, same as the Roles & access screen), not hardcoded.

`notify_staff(event_key, subject, body)` looks up every `NotificationRule`
row for that `event_key`, and for each one with a channel turned on,
sends to every `User` holding that role (via their `email`/`phone`
fields, not a Party's). Same fail-soft shape as `send_email`/`send_whatsapp`
above -- it never raises, and one recipient's missing/bad contact info
doesn't stop the rest of the role from being notified. Both channels
still go through the same simulated senders until a real WhatsApp/email
provider is wired up (see above) -- turning that on also makes staff
alerts real, with no further code change.

Events wired to a real trigger today:

| Event key | Fires from | Default roles (seed_demo) |
|---|---|---|
| `repair_ticket_created` | `repairs/views.py: RepairTicketViewSet.perform_create` | Repair Staff, Admin |
| `low_negative_feedback` | `portal/views.py: PortalFeedbackView.post`, rating ≤ 2 | Admin, Owner |
| `rental_approved` | `rentals/services.py: customer_decide`, customer approves (not staff on-behalf-of) | Admin, Sales Staff |
| `repair_approved` | `repairs/services.py: customer_decide` (single ticket) and `customer_decide_order` (bulk order) -- customer approval only | Admin, Repair Staff |
| `payment_received` | `sales/views.py: InvoiceViewSet.settle` and `repairs/views.py: RepairTicketViewSet.settle` | Accounts, Admin |

Add a new event by appending to `NotificationRule.EVENT_CHOICES` and
calling `notify_staff("your_event_key", subject, body)` from wherever
that event happens -- the Staff alerts screen picks it up automatically
via `GET /notification-rules/events/`, no frontend change needed.

## What's deliberately NOT wired up yet

- **`rentals/services.py`**'s approval-link issuer returns only a bare URL —
  no WhatsApp `wa.me` link, no email, nothing. (Repairs' equivalent in
  `repairs/services.py` already builds a `wa.me` click-to-chat link with the
  approval message pre-filled — that one needs no further work, it's real
  WhatsApp today.) Wire rentals the same way whenever convenient: either
  mirror repairs' `wa.me` approach, or route it through `send_whatsapp`/
  `send_email` for a fully automated send instead of a staff-click link.
- **`broadcast/views.py: CampaignViewSet`** (marketing campaigns) is
  **intentionally left fully simulated** (`perform_create` still fakes
  `sent`/`opened` counts with `random.randint`). A campaign targets many
  parties at once — wiring it to a real provider without first building
  real per-recipient send logic (and rate limiting, and unsubscribe
  handling) risks a mistake turning into a bulk message blast to every
  seeded/real customer in the database the moment `WHATSAPP_PROVIDER` is
  flipped to `meta_cloud`. Don't wire this up casually; treat it as its
  own task with its own review.
