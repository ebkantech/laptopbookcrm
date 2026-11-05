"""
Run a CRM API call as the staff member who is using the copilot.

The copilot has no data access or privileges of its own. Every read and every
confirmed write is a real internal request to the normal /api/ URL, carrying
the caller's own bearer token and active role/store headers. It therefore
passes through the same middleware and the same checks as a click in the CRM:
JWT, accounts.context, HasPerm, StoreScope, serializers, the domain rules and
Activity Logs. Nothing the model produces can reach further than that person.
"""
import json
from urllib.parse import urlencode

from django.core.handlers.wsgi import WSGIHandler
from django.test import RequestFactory

_handler = None
FORWARDED = ("HTTP_AUTHORIZATION", "HTTP_X_ACTIVE_ROLE", "HTTP_X_ACTIVE_STORE", "HTTP_X_FORWARDED_PROTO",
             "HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")


def _get_handler():
    global _handler
    if _handler is None:
        _handler = WSGIHandler()
    return _handler


class Result:
    def __init__(self, status, data):
        self.status = status
        self.data = data

    @property
    def ok(self):
        return 200 <= self.status < 300

    @property
    def error(self):
        data = self.data
        if isinstance(data, dict):
            if isinstance(data.get("detail"), str):
                return data["detail"]
            for value in data.values():
                if isinstance(value, list) and value and isinstance(value[0], str):
                    return value[0]
                if isinstance(value, str):
                    return value
        return f"The CRM refused this ({self.status})."


def call(request, method, path, query=None, body=None):
    """`path` is relative to /api/, e.g. "/invoices/12/". Returns a Result."""
    url = f"/api{path}"
    if query:
        url += f"?{urlencode(query)}"
    extra = {key: request.META[key] for key in FORWARDED if request.META.get(key)}
    inner = RequestFactory().generic(
        method.upper(), url, data=json.dumps(body) if body is not None else "",
        content_type="application/json", secure=request.is_secure(), HTTP_HOST=request.get_host(), **extra,
    )
    response = _get_handler().get_response(inner)
    try:
        data = json.loads(response.content.decode("utf-8")) if response.content else None
    except (ValueError, UnicodeDecodeError):
        data = None
    return Result(response.status_code, data)
