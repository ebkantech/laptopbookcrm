"""The apps (sidebar sections) a role can be given, and the permissions that
belong to each. The Roles & access screen uses this to show access app by
app: switching an app off for a role removes all of its permissions."""

APPS = [
    {"key": "dashboard", "label": "Dashboard", "view": "dashboard.view", "prefixes": ["dashboard"]},
    {"key": "storelocator", "label": "Store Locator", "view": "storelocator.view", "prefixes": ["storelocator"]},
    {"key": "invoices", "label": "Sales & Invoices", "view": "invoices.view", "prefixes": ["invoices", "payments"]},
    {"key": "parties", "label": "Parties", "view": "parties.view", "prefixes": ["parties"]},
    {"key": "repairs", "label": "Repairs & Service", "view": "repairs.view", "prefixes": ["repairs"]},
    {"key": "leads", "label": "On-site Service", "view": "leads.view", "prefixes": ["leads"]},
    {"key": "rentals", "label": "Rentals", "view": "rentals.view", "prefixes": ["rentals"]},
    {"key": "inventory", "label": "Inventory & Orders", "view": "inventory.edit", "prefixes": ["inventory", "orders"]},
    {"key": "warranty", "label": "Warranty", "view": "warranty.manage", "prefixes": ["warranty"]},
    {"key": "accounting", "label": "Accounting", "view": "cashbook.view", "prefixes": ["cashbook", "bankbook", "expenses"]},
    {"key": "reports", "label": "Reports", "view": "reports.view", "prefixes": ["reports"]},
    {"key": "broadcast", "label": "Broadcast & Portal", "view": "broadcast.send", "prefixes": ["broadcast", "portal"]},
    {"key": "settings", "label": "Settings & Staff", "view": "roles.manage", "prefixes": ["roles"]},
]


def app_for(codename):
    prefix = codename.split(".", 1)[0]
    for app in APPS:
        if prefix in app["prefixes"]:
            return app["key"]
    return "other"


def catalog(codenames):
    """APPS with the permission codenames present in the database filled in."""
    out = [{"key": a["key"], "label": a["label"], "view": a["view"], "permissions": []} for a in APPS]
    other = {"key": "other", "label": "Other", "view": None, "permissions": []}
    index = {a["key"]: a for a in out}
    for code in sorted(codenames):
        index.get(app_for(code), other)["permissions"].append(code)
    return [a for a in out + [other] if a["permissions"]]
