from django.db.models import Q

from .models import Ticket


def apply_filters(qs, params, user, include_status=True):
    q = params.get("q", "").strip()
    if q:
        cond = (
            Q(title__icontains=q) | Q(requester__first_name__icontains=q)
            | Q(requester__last_name__icontains=q) | Q(asset__code__icontains=q)
        )
        digits = q.upper().removeprefix("TK-").strip()
        if digits.isdigit() and len(digits) <= 9:           # TK-000184 o 184
            cond |= Q(number=int(digits))
        qs = qs.filter(cond)

    if include_status:
        status = params.get("status", "")
        if status == "open":
            qs = qs.active()
        elif status in Ticket.Status.values:
            qs = qs.filter(status=status)

    if params.get("priority", "").isdigit():
        qs = qs.filter(priority_id=int(params["priority"]))
    if params.get("category", "").isdigit():
        qs = qs.filter(category_id=int(params["category"]))
    if params.get("department", "").isdigit():
        qs = qs.filter(department_id=int(params["department"]))

    assigned = params.get("assigned", "")
    if assigned == "me":
        qs = qs.filter(assigned_to=user)
    elif assigned == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned.isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))

    if params.get("sla") == "breached":
        qs = qs.sla_breached()
    return qs