from datetime import date

MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def last_n_months(n):
    """Last n calendar months including the current one, oldest first,
    as (year, month) tuples. Same logic as dashboard.views._last_n_months
    -- kept as its own small copy here (not a cross-app import) so the
    reports app has no dependency on the dashboard app existing/being
    installed, matching how every other app in this project is
    self-contained."""
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(months))


def month_label(year, month):
    return f"{MONTH_ABBR[month]} {year}"
