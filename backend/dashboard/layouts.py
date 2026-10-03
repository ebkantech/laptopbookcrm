from .models import DashboardLayout, DashboardWidget


def visible_sections(user):
    """
    Which dashboard sections the user's role can see -- the single
    source for both DashboardView's per-section queries and the widget
    layout below. A superuser holds every permission via has_perm_code(),
    so Owner/Admin see everything. See docs/PERMISSIONS.md.
    """
    can_repairs = user.has_perm_code("repairs.view")
    return {
        # Repair Staff don't hold inventory.edit (a stock *management*
        # permission) but still need to see what's on the shelf, so the
        # stock section's visibility is widened to repairs.view too.
        DashboardWidget.STOCK: user.has_perm_code("inventory.edit") or can_repairs,
        DashboardWidget.SALES: user.has_perm_code("invoices.view"),
        DashboardWidget.REPAIRS: can_repairs,
        DashboardWidget.RENTALS: user.has_perm_code("rentals.view"),
    }


def _layout_for(user):
    """The user's own layout, else their role's, else None (catalog defaults)."""
    layout = DashboardLayout.objects.filter(user=user).first()
    if layout is None and user.role_id:
        layout = DashboardLayout.objects.filter(role_id=user.role_id).first()
    return layout


def effective_layout(user):
    """
    The ordered list of widgets this user should see, each as a plain
    dict ready to serialise. Widgets in sections the user's role can't
    see are dropped regardless of what a saved layout says, and active
    catalog widgets missing from a saved layout (e.g. added after the
    layout was saved) are appended with their defaults so they don't
    silently disappear.
    """
    sections = visible_sections(user)
    widgets = [w for w in DashboardWidget.objects.filter(is_active=True) if sections.get(w.section)]
    layout = _layout_for(user)
    placed = {}
    if layout is not None:
        placed = {item.widget_id: item for item in layout.items.all()}

    entries = []
    for w in widgets:
        item = placed.get(w.id)
        if item is not None:
            entry = {
                "position": item.position, "width": item.width, "height": item.height,
                "visible": item.is_visible, "settings": {**w.default_settings, **item.settings},
            }
        else:
            # Sort unplaced widgets after every saved placement, in catalog order.
            offset = 1000 if layout is not None else 0
            entry = {
                "position": offset + w.default_order, "width": w.default_width, "height": w.default_height,
                "visible": True, "settings": dict(w.default_settings),
            }
        entry.update({
            "key": w.key, "title": w.title, "kind": w.kind, "chart_type": w.chart_type,
            "section": w.section, "data_keys": w.data_keys,
            "respects_filters": w.respects_filters, "link_page": w.link_page,
        })
        entries.append(entry)

    entries.sort(key=lambda e: (e["position"], e["key"]))
    return {
        "source": "user" if layout and layout.user_id else "role" if layout else "default",
        "grid_columns": DashboardWidget.GRID_COLUMNS,
        "widgets": entries,
    }
