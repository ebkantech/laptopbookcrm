"""
The sellable modules and how they depend on each other. This is the only place
that says so: packages, the access block and the screens all read it.

CORE is in every package. Every other module lists what it needs: "all" must
all be present, and at least one of "any". Modules import each other, so
nothing is ever uninstalled: a module outside the package is only refused.
"""
from django.core.exceptions import ValidationError

CORE = ("parties", "dashboard", "storelocator", "settings")

DEPENDS = {
    "invoices": {},
    "inventory": {},
    "repairs": {"all": ("invoices", "inventory")},
    "leads": {"all": ("invoices", "inventory", "repairs")},
    "rentals": {"all": ("invoices", "inventory")},
    "warranty": {"all": ("invoices", "repairs")},
    "accounting": {"all": ("invoices",)},
    "reports": {"all": ("invoices",)},
    "portal": {"all": ("invoices",), "any": ("repairs", "rentals")},
    "broadcast": {},
    "copilot": {},
}

LABELS = {
    "invoices": "Sales & Invoices", "inventory": "Inventory & Orders", "repairs": "Repairs & Service",
    "leads": "On-site Service", "rentals": "Rentals", "warranty": "Warranty", "accounting": "Accounting",
    "reports": "Reports", "portal": "Customer Portal", "broadcast": "Broadcast", "copilot": "AI-Staff",
}

# The first path segments under /api/ that belong to each module. Invoices and
# inventory aren't here: every package has them.
API_PREFIXES = {
    "repairs": ("tickets", "repair-orders", "repair-staff-report", "public/repair-approvals",
                "public/repair-order-approvals"),
    "leads": ("leads", "public/lead-approvals"),
    "rentals": ("rentals", "rental-assets", "rental-issues", "rental-lines", "rental-photos",
                "public/rental-approvals"),
    "warranty": ("warranties", "warranty-claims"),
    "accounting": ("cash-entries", "bank-entries", "bank-accounts", "expenses", "expense-categories",
                   "expense-attachments"),
    "reports": ("reports",),
    "portal": ("portal", "portal-invites", "portal-access-logs"),
    "broadcast": ("campaigns",),
    "copilot": ("copilot",),
}

# Permission prefixes, so the sidebar and buttons hide with the module.
PERMISSION_PREFIXES = {
    "repairs": ("repairs",), "leads": ("leads",), "rentals": ("rentals",), "warranty": ("warranty",),
    "accounting": ("cashbook", "bankbook", "expenses"), "reports": ("reports",), "portal": ("portal",),
    "broadcast": ("broadcast",), "copilot": ("copilot",),
}


def label(module):
    return LABELS.get(module, module)


def missing_for(module, chosen):
    """(all still needed, any-of groups with nothing chosen)."""
    rule = DEPENDS[module]
    needed = [dep for dep in rule.get("all", ()) if dep not in chosen]
    choice = rule.get("any", ())
    return needed, (choice if choice and not set(choice) & set(chosen) else ())


def with_dependencies(modules):
    """The modules plus everything they need. A choice of "one of these" can't
    be made for the seller, so it is refused rather than guessed."""
    unknown = [module for module in modules if module not in DEPENDS]
    if unknown:
        raise ValidationError(f"Unknown modules: {', '.join(unknown)}.")
    chosen = set(modules)
    pending = list(modules)
    while pending:
        needed, _ = missing_for(pending.pop(), chosen)
        chosen.update(needed)
        pending.extend(needed)
    for module in sorted(chosen):
        _, choice = missing_for(module, chosen)
        if choice:
            options = " or ".join(label(option) for option in choice)
            raise ValidationError(f"{label(module)} needs {options}.")
    return sorted(chosen)


def dependents(module, chosen):
    """Which chosen modules would break if `module` were removed."""
    remaining = set(chosen) - {module}
    return sorted(other for other in remaining if any(missing_for(other, remaining)))
