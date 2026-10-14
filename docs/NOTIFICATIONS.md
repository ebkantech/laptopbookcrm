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

**By default, both are test/simulated backends — nothing leaves your
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

`send_whatsapp()` in `crmbook_backend/notify.py` sends through Meta's
WhatsApp Cloud API when `WHATSAPP_PROVIDER=meta_cloud`. Credentials live in
`backend/.env` only (git-ignored) -- never in code. See `.env.example`.

```
WHATSAPP_PROVIDER=meta_cloud
WHATSAPP_PHONE_NUMBER_ID=<Meta dashboard > WhatsApp > API Setup>
WHATSAPP_ACCESS_TOKEN=<temporary dashboard token (~24 h) or System User token>
# optional
WHATSAPP_GRAPH_API_VERSION=v25.0
WHATSAPP_DEFAULT_COUNTRY_CODE=91
```

What `send_whatsapp()` returns:
- `sent` + `provider_id` (Meta's `wamid...`) -- Meta **accepted** the
  message. Not proof of delivery: delivered/read/failed arrive later as
  webhooks (see "Delivery status" below).
- `failed` + `reason` + `error_code` -- missing/invalid config, invalid
  number, Meta rejection (`meta_<code>`), timeout, network error, or a 2xx
  without a message id (`malformed_response`). `reason` is safe to show
  staff; the token is never logged or returned.
- `simulated` (console provider) / `skipped` (no phone on file).

Numbers are normalized to digits with country code (`9876543210` ->
`919876543210`).

**Number check:** the Cloud API has no "does this number have WhatsApp"
lookup (the old `/contacts` call belonged to the retired On-Premises API),
so with `meta_cloud` `check_whatsapp_number()` returns "unknown" and sends
are still attempted.

### Templates and the 24-hour window

Free text is only accepted within 24 hours of the customer's last message
to your business number. Outside it Meta needs an **approved template**
(otherwise error 131047, usually reported asynchronously). Templates are
opt-in per message kind and are named in the environment, never guessed:

| Kind | Env var | Template body parameters (in order) |
|---|---|---|
| Rental approval link | `WHATSAPP_TEMPLATE_RENTAL_APPROVAL` | {{1}} customer name, {{2}} agreement code, {{3}} approval link |
| Portal invite / reset link | `WHATSAPP_TEMPLATE_PORTAL_INVITE` | {{1}} customer name, {{2}} portal link, {{3}} link expiry |

Language: `WHATSAPP_TEMPLATE_<KIND>_LANGUAGE`, else
`WHATSAPP_TEMPLATE_LANGUAGE`, else `en` -- must match the approved
template's language exactly (e.g. `en` vs `en_US`). With no template set,
the free-text message is sent. Repair, rent-invoice and staff-alert
messages have no template hook yet and always send free text.

### Test number

Meta's test number can only message numbers added to its allowed list
(dashboard > WhatsApp > API Setup > "To"); others fail with 131030, which
the CRM reports as such.

### Delivery status

`WhatsAppDeliveryLog` gets a `sent` row whenever Meta accepts a message.
Meta's webhook is `api/whatsapp/meta-webhook/` (`portal/meta_webhook.py`):
GET verification with `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, POSTs checked against
`X-Hub-Signature-256` with `WHATSAPP_APP_SECRET` (either unset = refuse
all). Its `statuses` move chat messages and delivery-log rows to
delivered / read / failed -- the only way anything shows "Delivered".
Inbound customer replies are not stored yet. The older
`portal/whatsapp-webhook/` (custom shared-secret format) is unchanged.

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
| Ad-hoc customer message (Parties chat, Rentals "Chat on WhatsApp") | WhatsApp: sent via `send_whatsapp`, outcome stored on the Message; Email: CRM record only | `parties.manage` | `parties/views.py: PartyViewSet.send_message` |
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

- **Rental approval links** return both a `wa.me` click-to-chat link and,
  when `WHATSAPP_PROVIDER=meta_cloud`, can be sent through the API with
  `POST /rentals/<id>/approval-link/send-whatsapp/ {"approval_url": ...}`
  (`rentals/services.py: send_approval_link_whatsapp`). That endpoint only
  accepts the link just issued for that agreement (its token must hash to
  the current pending approval) -- it never issues a new token, and an
  accepted send can't be repeated. The raw link is not stored on the
  customer's message thread, because anyone holding it can approve.
- **The CRM chat** (Parties page and the Rentals "Chat on WhatsApp" modal --
  one composer, `POST /parties/<id>/messages/`) saves the message, then
  sends WhatsApp ones to the party's own `Party.phone` through
  `send_whatsapp()` (`parties/whatsapp.py`), outside any DB transaction.
  `Message.delivery_status` records the outcome: `sent` (Meta accepted),
  `failed` (+ `delivery_error`), `unknown` (timeout -- may have gone out),
  `simulated` (console mode). Failed/simulated messages can be edited and
  resent in place (`.../messages/<id>/retry/`); `unknown` needs
  `{"confirm": true}`; accepted ones are locked. Free text only -- outside
  the 24-hour window Meta fails it (131047, reported via the webhook).
  Email messages remain CRM records only.
- **`broadcast/views.py: CampaignViewSet`** (marketing campaigns) is
  **intentionally left fully simulated** (`perform_create` still fakes
  `sent`/`opened` counts with `random.randint`). A campaign targets many
  parties at once — wiring it to a real provider without first building
  real per-recipient send logic (and rate limiting, and unsubscribe
  handling) risks a mistake turning into a bulk message blast to every
  seeded/real customer in the database the moment `WHATSAPP_PROVIDER` is
  flipped to `meta_cloud`. Don't wire this up casually; treat it as its
  own task with its own review.
