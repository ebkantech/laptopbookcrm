"""Repair staff performance report -- Admin / Super Admin only."""
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import HasPerm
from accounts.store_scope import StoreScope

from .models import RepairTicket


def _day_bounds(day):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(day, time.min), tz),
            timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz))


def _hours(delta):
    return round(delta.total_seconds() / 3600, 1)


def period_range(params, today):
    period = params.get("period") or "month"
    if period == "today":
        return period, today, today
    if period == "month":
        return period, today.replace(day=1), today
    if period == "year":
        return period, today.replace(month=1, day=1), today
    if period == "custom":
        try:
            start = datetime.strptime(params.get("date_from", ""), "%Y-%m-%d").date()
            end = datetime.strptime(params.get("date_to", ""), "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError({"detail": "Pick a valid from and to date."})
        if end < start:
            raise ValidationError({"detail": "The 'to' date is before the 'from' date."})
        return period, start, end
    raise ValidationError({"period": "Use today, month, year or custom."})


def _job(ticket, now):
    start = ticket.assigned_at or ticket.started_at or _day_bounds(ticket.received)[0]
    due = ticket.due_at
    end = ticket.ready_at
    row = {
        "id": ticket.pk, "code": ticket.code, "party": ticket.party.name,
        "device": f"{ticket.brand} {ticket.model_name}".strip(), "store": ticket.stock_point.name,
        "status": ticket.status, "assigned_at": ticket.assigned_at, "started_at": ticket.started_at,
        "ready_at": end, "due_at": due,
        "diagnosed_at": ticket.diagnosed_at, "diagnosis_note": ticket.diagnosis_note,
        "hours_to_diagnose": _hours(ticket.diagnosed_at - start) if ticket.diagnosed_at else None,
    }
    if end:
        row["hours_taken"] = _hours(end - start)
        late = end - due
    else:
        row["hours_open"] = _hours(now - start)
        late = now - due
    row["delayed"] = late.total_seconds() > 0
    row["delay_hours"] = _hours(late) if row["delayed"] else 0
    return row


def build_report(user, params):
    now = timezone.now()
    today = timezone.localdate()
    period, start, end = period_range(params, today)
    p_start, p_end = _day_bounds(start)[0], _day_bounds(end)[1]
    scope = StoreScope(user)

    staff = User.objects.filter(is_active=True).select_related("role", "stock_point")
    staff = [u for u in staff if u.has_perm_code("repairs.manage") and not u.is_superuser and not (u.role_id and u.role.slug == "owner")]
    if not scope.all:
        staff = [u for u in staff if u.stock_point_id == scope.store_id or u.pk == user.pk]
    staff_ids = [u.pk for u in staff]

    tickets = (RepairTicket.objects.select_related("party", "stock_point")
               .filter(Q(worked_by_id__in=staff_ids, ready_at__isnull=False) | Q(assigned_to_id__in=staff_ids))
               .exclude(status=RepairTicket.DELIVERED, ready_at__isnull=True))
    done_by, open_by = {}, {}
    for t in tickets:
        if t.ready_at and t.worked_by_id in staff_ids:
            done_by.setdefault(t.worked_by_id, []).append(t)
        elif not t.ready_at and t.assigned_to_id in staff_ids and t.status != RepairTicket.DELIVERED:
            open_by.setdefault(t.assigned_to_id, []).append(t)

    windows = {"today": _day_bounds(today), "month": (_day_bounds(today.replace(day=1))[0], _day_bounds(today)[1]),
               "year": (_day_bounds(today.replace(month=1, day=1))[0], _day_bounds(today)[1])}
    rows = []
    for u in staff:
        done = done_by.get(u.pk, [])
        in_period = [t for t in done if p_start <= t.ready_at < p_end]
        jobs = [_job(t, now) for t in sorted(in_period, key=lambda t: t.ready_at, reverse=True)]
        open_jobs = [_job(t, now) for t in sorted(open_by.get(u.pk, []), key=lambda t: t.due_at)]
        taken = [j["hours_taken"] for j in jobs]
        rows.append({
            "id": u.pk, "name": u.get_full_name() or u.username, "store": u.stock_point.name if u.stock_point_id else "",
            "counts": {k: sum(1 for t in done if a <= t.ready_at < b) for k, (a, b) in windows.items()},
            "period": {
                "done": len(jobs), "on_time": sum(1 for j in jobs if not j["delayed"]),
                "delayed": sum(1 for j in jobs if j["delayed"]),
                "avg_hours": round(sum(taken) / len(taken), 1) if taken else None,
                "total_delay_hours": round(sum(j["delay_hours"] for j in jobs), 1),
            },
            "open": len(open_jobs), "overdue": sum(1 for j in open_jobs if j["delayed"]),
            "jobs": jobs, "open_jobs": open_jobs,
        })
    rows.sort(key=lambda r: (-r["period"]["done"], r["name"].lower()))
    return {"period": period, "date_from": start, "date_to": end, "staff": rows,
            "totals": {"done": sum(r["period"]["done"] for r in rows), "delayed": sum(r["period"]["delayed"] for r in rows),
                       "overdue_open": sum(r["overdue"] for r in rows)}}


class RepairStaffReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    required_perm = "repairs.assign"

    def get(self, request):
        return Response(build_report(request.user, request.query_params))
