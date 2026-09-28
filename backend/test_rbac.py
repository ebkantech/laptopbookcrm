"""
Throwaway RBAC diagnostic. Run this while `python manage.py runserver` is
running in another terminal (same backend/ folder, same venv active):

    python test_rbac.py

It logs in as each of the 6 seeded users and hits a handful of endpoints
that should now be gated differently per role, printing the HTTP status
code for each. 200/201 = allowed, 403 = blocked, 401 = login itself failed.

Delete this file once you're done -- it's not part of the app.
"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"

# username -> (role slug, expected access per endpoint)
USERS = ["aman.kapoor", "vikram.sethi", "naina.joshi", "suresh.rana", "ritu.sharma", "deepa.iyer"]
PASSWORD = "crmbook123"

ENDPOINTS = [
    ("GET", "/api/parties/"),
    ("GET", "/api/tickets/"),          # repairs.view
    ("GET", "/api/cash-entries/"),     # cashbook.view
    ("GET", "/api/whatsapp-orders/"),  # orders.manage
    ("GET", "/api/campaigns/"),        # broadcast.send
    ("GET", "/api/rentals/"),          # rentals.view (adjust if your router prefix differs)
]


def login(username):
    req = urllib.request.Request(
        f"{BASE}/api/auth/token/",
        data=json.dumps({"username": username, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["access"]
    except urllib.error.HTTPError as e:
        print(f"  LOGIN FAILED for {username}: {e.code} {e.read()[:200]}")
        return None


def call(method, path, token):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def main():
    for username in USERS:
        print(f"\n=== {username} ===")
        token = login(username)
        if not token:
            continue
        for method, path in ENDPOINTS:
            status = call(method, path, token)
            print(f"  {method} {path:<28} -> {status}")


if __name__ == "__main__":
    main()
