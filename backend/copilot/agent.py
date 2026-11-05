"""The staff chat loop: the model may read, and may prepare changes for confirmation."""
import json
import time

from django.conf import settings

from . import catalog, dispatch, llm, prompts, redact, search
from .models import ChatMessage, ProposedAction

MAX_ROUNDS = 6
MAX_PROPOSALS = 5
HISTORY = 16


def _tools(actions, searchable):
    tools = [{
        "name": "crm_read",
        "description": "Read CRM records as the signed-in staff member.",
        "input_schema": {"type": "object", "required": ["path"], "properties": {
            "path": {"type": "string", "description": "e.g. /invoices/ or /tickets/42/"},
            "query": {"type": "object", "description": "Filters, e.g. {\"status\": \"Overdue\"}"},
        }},
    }]
    if searchable:
        tools.append({
            "name": "crm_search",
            "description": "Find records by meaning or partial details across customers, invoices, repairs, products, rentals and on-site leads. "
                           "Use it when you don't know the id or exact filter, then crm_read for more detail.",
            "input_schema": {"type": "object", "required": ["query"], "properties": {
                "query": {"type": "string"},
                "types": {"type": "array", "items": {"type": "string", "enum": list(search.DETAIL)}},
            }},
        })
    if actions:
        tools.append({
            "name": "propose_action",
            "description": "Prepare a change for the staff member to confirm.",
            "input_schema": {"type": "object", "required": ["action", "params"], "properties": {
                "action": {"type": "string", "enum": [a.key for a in actions]},
                "params": {"type": "object", "description": "The action's ids and fields."},
            }},
        })
    return tools


def run_read(request, data):
    path = str(data.get("path") or "")
    query = data.get("query") if isinstance(data.get("query"), dict) else None
    if not catalog.read_allowed(path):
        return {"error": "That path isn't available to the copilot."}
    result = dispatch.call(request, "GET", path, query={k: str(v) for k, v in (query or {}).items()})
    if not result.ok:
        return {"error": result.error, "status": result.status}
    return _mark_pages(fit(redact.clean(result.data)))


def fit(data):
    """Trim a long list to what fits and say so, so the model never treats part of a list as all of it."""
    rows = data.get("results") if isinstance(data, dict) else data
    if not isinstance(rows, list) or len(json.dumps(data, default=str)) <= redact.LIMIT:
        return data
    total = data.get("count", len(rows)) if isinstance(data, dict) else len(rows)
    has_more_pages = isinstance(data, dict) and bool(data.get("next"))
    kept = list(rows)
    while kept and len(json.dumps(kept, default=str)) > redact.LIMIT:
        kept.pop()
    return {"results": kept, "showing": len(kept), "total": total, "complete": False, "more_pages": has_more_pages,
            "note": f"Only {len(kept)} of {total} rows are here. Say so, or narrow the request with filters."}


def _mark_pages(data):
    """A list that fits but has further pages is still only part of the data."""
    if isinstance(data, dict) and data.get("next") and "complete" not in data:
        rows = data.get("results") or []
        return {**data, "complete": False, "showing": len(rows), "total": data.get("count"),
                "note": f"Only {len(rows)} of {data.get('count')} rows are here. Use query page=2 for more, or say the list is partial."}
    return data


def _target(request, action, ids):
    """Name the record from the CRM itself, as this user. A record they can't reach stops the proposal here."""
    if not action.describe:
        return "", None
    path, describe, _check = action.describe
    result = dispatch.call(request, "GET", path.format(**ids))
    if not result.ok:
        return "", result.error
    return describe(result.data)[:240], None


def propose(request, conversation, data):
    action = catalog.ACTIONS.get(str(data.get("action") or ""))
    if action is None or action not in catalog.available(request.user):
        return {"error": "This person isn't allowed to do that."}
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    ids = {}
    for name in action.ids:
        value = params.get(name)
        if isinstance(value, bool) or not str(value).isdigit():
            return {"error": f"{name} must be the record's numeric id."}
        ids[name] = int(value)
    missing = [name for name in action.required if params.get(name) in (None, "")]
    if missing:
        return {"error": f"Ask the user for: {', '.join(missing)}."}
    body = {name: params[name] for name in (*action.required, *action.optional) if name in params}
    if action.method == "PATCH" and not body:
        return {"error": "There is nothing to change."}
    target, error = _target(request, action, ids)
    if error:
        return {"error": error}
    proposal = ProposedAction.objects.create(
        conversation=conversation, user=request.user, action_key=action.key, label=action.label, target=target,
        method=action.method, path=action.path.format(**ids), body=body,
        active_role=request.META.get("HTTP_X_ACTIVE_ROLE", "")[:20],
        active_store=request.META.get("HTTP_X_ACTIVE_STORE", "")[:20],
    )
    return {"status": "waiting_for_confirmation", "proposal": proposal.id}


def history(conversation):
    rows = list(conversation.messages.order_by("-created_at", "-id")[:HISTORY])
    messages = [{"role": row.role, "content": row.text} for row in reversed(rows)]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def chat(request, conversation, text):
    ChatMessage.objects.create(conversation=conversation, role=ChatMessage.USER, text=text)
    actions = catalog.available(request.user)
    system = prompts.staff_system(request.user, actions)
    tools = _tools(actions, search.available())
    messages = history(conversation)
    deadline = time.monotonic() + settings.COPILOT_TURN_SECONDS
    proposals = 0
    reply = ""
    finished = False
    for _round in range(MAX_ROUNDS):
        if time.monotonic() > deadline:
            reply = reply or "That took too long, so I stopped. Try a narrower question."
            break
        result = llm.complete(system, messages, tools)
        reply = llm.text_of(result) or reply
        calls = [block for block in result.get("content", []) if block.get("type") == "tool_use"]
        if not calls:
            finished = True
            break
        messages.append({"role": "assistant", "content": result["content"]})
        answers = []
        for block in calls:
            if block.get("name") == "crm_read":
                output = run_read(request, block.get("input") or {})
            elif block.get("name") == "crm_search":
                data = block.get("input") or {}
                kinds = data.get("types") if isinstance(data.get("types"), list) else None
                output = search.search(request, data.get("query"), kinds)
            elif block.get("name") == "propose_action" and proposals < MAX_PROPOSALS:
                output = propose(request, conversation, block.get("input") or {})
                proposals += "proposal" in output
            else:
                output = {"error": "Not available."}
            answers.append({"type": "tool_result", "tool_use_id": block.get("id"),
                            "content": json.dumps(output, default=str)[:redact.MAX_CHARS]})
        messages.append({"role": "user", "content": answers})
    else:
        if not proposals:
            reply = reply or "I couldn't finish that in one go. Try a narrower question."
    if proposals and not finished:
        reply = f"I've prepared {proposals} item{'s' if proposals != 1 else ''} below. Check each one, then Confirm or Reject."
    reply = reply or "Done."
    ChatMessage.objects.create(conversation=conversation, role=ChatMessage.ASSISTANT, text=reply)
    return reply
