# Staff Copilot

An assistant inside the CRM (the Copilot button, bottom right). It has three tabs:

- **Chat**: ask in plain language. It reads CRM records and prepares changes.
- **My work**: what needs doing now for this person's role and store.
- **Customers**: customer messages waiting for an answer, with a suggested reply.

## Setup

1. Add `ANTHROPIC_API_KEY=...` to `backend/.env` locally, and to the Render environment, or use a free provider (below). Never commit a key.
2. `python manage.py migrate` (adds the Copilot tables, `copilot.use` for every existing role, and the portal message channel).
3. `npm run build` in `frontend/`.
4. Run gunicorn with `--timeout 120`: one chat turn can take over a minute, and the default 30 seconds would cut it off.

### Trying it for free

Set these in `backend/.env` and restart the backend:

```env
COPILOT_PROVIDER=gemini
COPILOT_API_KEY=your-free-key
```

| Provider | Key from | Default model |
|---|---|---|
| `gemini` | aistudio.google.com | `gemini-3.8-flash` |
| `groq` | console.groq.com | `openai/gpt-oss-120b` |
| `openrouter` | openrouter.ai (set `COPILOT_MODEL` to a `:free` model) | none |
| `ollama` | no key; runs on your own PC, local backend only | `llama3.1` |

Free tiers have low rate limits, and models change, so set `COPILOT_MODEL` if a
default stops working. Use demo data only: free tiers may let the provider keep
or review what is sent. Check their terms before using real customer records.

To hide Copilot from a role, remove `copilot.use` in Settings > Roles & access.

## How it stays within a person's access

The copilot has no access of its own. Every read and every confirmed change is
an internal request to the normal `/api/` URL with that person's own token and
active role and store (`copilot/dispatch.py`), so `HasPerm`, `StoreScope`, the
serializers, the business rules and Activity Logs all apply exactly as they do
for a click in the CRM.

| Rule | Where |
|---|---|
| Reads are limited to an allowlist. Sign-in, staff accounts, activity logs, portal codes, customer ID documents and uploaded files are never fetched. | `copilot/catalog.py` `READS` |
| Changes are limited to a fixed list, offered only if the role holds the permission. The model can't choose a URL or add fields. | `copilot/catalog.py` `ACTIONS` |
| Nothing changes until the person presses Confirm on a card showing the record and every value. The record's name on the card comes from the CRM, not the model. | `copilot/agent.py`, `copilot/actions.py` |
| A proposal runs once, only for the person it was made for, only under the same role and store, and expires after 30 minutes. | `copilot/actions.py` |
| After a change that has an expected result, the record is read back and the card shows what the CRM now says. | `copilot/actions.py` `_verify` |

To add an ability, add an `Action` to `ACTIONS` and a test. Anything not listed
there can't be done through Copilot, which will point the person to the right screen.

## Search by meaning

Copilot can find records from a rough description ("the customer with the
broken Dell screen") as well as exact filters. It covers customers, invoices,
repairs, products, rentals and on-site leads.

1. Run `python manage.py copilot_index` to build the search index. Phone numbers and emails are never included.
2. Run it again on a schedule, daily for example, or after a large import. It only processes what changed, and if it stops part-way, running it again carries on.

With `COPILOT_PROVIDER=gemini` nothing else is needed. Other providers need
`COPILOT_EMBED_MODEL`; for LM Studio, load an embedding model and use its
identifier. Anthropic has no embeddings, so with Anthropic chat set
`COPILOT_EMBED_PROVIDER=gemini` and `COPILOT_EMBED_API_KEY` too. Changing the
embedding model means running the command again.

The index only finds candidates. Each match is opened through the CRM's API as
the person asking, so records outside their role or store are dropped, and
the answer always uses live data (`copilot/search.py`). Without an index,
Copilot works as before using filters.

## Customer messages

Queries arrive on the party's thread:

- **WhatsApp**: stored by the existing Meta webhook. A number that matches no party is logged and dropped, as it was before.
- **Email**: the CRM has no inbound email, so only messages already on a thread appear.
- **Customer portal**: the new "Message us" section (`/api/portal/messages/`).

Nothing automated ever replies. A draft is written only when a staff member
presses Draft reply, using that person's access, so it can't include another
store's records. It has no tools, and the customer's text is passed as marked
data. Staff edit and send; sending uses the normal thread endpoint, always to
the party on file.

## Data sent to the AI service

Requests go to the configured AI provider. Records used to answer a question are sent,
including customer names, purchase details and message text. Phones, emails,
GSTINs and addresses are masked first; passwords, tokens, codes, links and ID
documents are removed (`copilot/redact.py`). Check this against your privacy
notice and the Digital Personal Data Protection Act before using real customer data.

## Costs and limits

Each chat message or draft is a paid API call. `COPILOT_THROTTLE_RATE` caps it
per staff member (default 120/hour); `PORTAL_MESSAGE_THROTTLE_RATE` caps portal
messages per customer (default 30/hour).

Tests: `python manage.py test copilot`. They use a scripted stand-in for the AI
service, including requests a manipulated model might make.
