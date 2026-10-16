from datetime import timedelta

from django.utils import timezone

from apps.core.utils import format_minutes

from .models import BusinessSchedule
from .workcalendar import Calendar, add_business_time, business_time_between

WARNING_PCT = 75         # a partir de este % consumido el estado pasa a "Por vencer"
ZERO = timedelta(0)

# estado: (etiqueta, clases del distintivo, clase de la barra)
STATES = {
    "ok": ("En tiempo", "bg-green-100 text-green-800", "bg-green-500"),
    "warning": ("Por vencer", "bg-amber-100 text-amber-800", "bg-amber-500"),
    "breached": ("Incumplido", "bg-red-100 text-red-800", "bg-red-500"),
    "paused": ("En pausa", "bg-purple-100 text-purple-800", "bg-purple-400"),
    "met": ("Cumplido", "bg-green-100 text-green-800", "bg-green-500"),
    "missed": ("Incumplido", "bg-red-100 text-red-800", "bg-red-500"),
    "na": ("No aplica", "bg-slate-100 text-slate-600", "bg-slate-300"),
}


def get_calendar():
    s = BusinessSchedule.get()
    days = frozenset(s.workday_numbers)
    return Calendar(
        workdays=days, start=s.start_time, end=s.end_time,
        tz=timezone.get_current_timezone(), always=s.is_24x7 or not days,
    )


# ---------------- Plazos de un ticket ----------------

def apply_deadlines(ticket, cal=None):
    """Calcula (sin guardar) los plazos del ticket según su prioridad, desde su fecha de creación."""
    cal = cal or get_calendar()
    p = ticket.priority
    ticket.response_due_at = add_business_time(cal, ticket.created_at, timedelta(minutes=p.response_minutes))
    ticket.resolution_due_at = add_business_time(
        cal, ticket.created_at,
        timedelta(minutes=p.resolution_minutes, seconds=ticket.sla_paused_seconds),
    )


def pause(ticket, now):
    """Detiene el reloj (sin guardar). No hace nada si ya estaba detenido."""
    if ticket.sla_paused_at is None:
        ticket.sla_paused_at = now


def resume(ticket, now, cal=None):
    """Reanuda el reloj (sin guardar): suma el tiempo laboral de la pausa y recalcula los plazos."""
    if ticket.sla_paused_at is None:
        return
    cal = cal or get_calendar()
    paused = business_time_between(cal, ticket.sla_paused_at, now)
    ticket.sla_paused_seconds += int(paused.total_seconds())
    ticket.sla_paused_at = None
    apply_deadlines(ticket, cal)


def recalculate_open_tickets():
    """Recalcula los plazos de todos los tickets sin resolver (al cambiar el horario). Devuelve cuántos."""
    from apps.tickets.models import Ticket          # import local: evita un ciclo entre apps

    cal = get_calendar()
    count = 0
    for ticket in Ticket.objects.alive().active().select_related("priority"):
        apply_deadlines(ticket, cal)
        ticket.save(update_fields=["response_due_at", "resolution_due_at"])
        count += 1
    return count


# ---------------- Evaluación (qué mostrar) ----------------

def _fmt(td):
    minutes = int(td.total_seconds() // 60)
    return "menos de 1 min" if minutes < 1 else format_minutes(minutes)


def _fmt_dt(value):
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")


def _result(kind, state, *, due, done_at=None, pct=0, detail="", short=""):
    label, badge, bar = STATES[state]
    return {
        "kind": kind, "state": state, "label": label, "badge": badge, "bar": bar,
        "pct": pct, "due_at": due, "done_at": done_at, "detail": detail, "short": short,
    }


def evaluate_metric(cal, *, kind, created, due, base, done_at, paused_at, now, cancelled=False):
    """
    Estado de un plazo. `base` es el tiempo que otorga la prioridad (sin contar pausas).
    El reloj se congela en `done_at` (si ya se cumplió) o en `paused_at` (si está en pausa).
    """
    if cancelled or due is None:
        return _result(kind, "na", due=due, detail="No aplica.")

    ref = done_at or paused_at or now
    if ref <= due:
        remaining, excess = business_time_between(cal, ref, due), ZERO
        used = base - remaining
        pct = int(max(0.0, min(1.0, used / base)) * 100) if base > ZERO else 100
    else:
        remaining, excess, pct = ZERO, business_time_between(cal, due, ref), 100

    if done_at:
        if done_at <= due:
            return _result(kind, "met", due=due, done_at=done_at, pct=pct,
                           detail=f"Cumplido el {_fmt_dt(done_at)}.")
        return _result(kind, "missed", due=due, done_at=done_at, pct=100,
                       detail=f"Cumplido el {_fmt_dt(done_at)}, con {_fmt(excess)} de retraso.",
                       short=f"+{_fmt(excess)}" if excess >= timedelta(minutes=1) else "")
    if paused_at and paused_at <= due:
        return _result(kind, "paused", due=due, pct=pct,
                       detail=f"Reloj en pausa mientras se espera al usuario. Quedan {_fmt(remaining)}.",
                       short=_fmt(remaining))
    if now > due:
        return _result(kind, "breached", due=due, pct=100,
                       detail=f"Excedido por {_fmt(excess)}.",
                       short=f"+{_fmt(excess)}" if excess >= timedelta(minutes=1) else "")
    state = "warning" if pct >= WARNING_PCT else "ok"
    return _result(kind, state, due=due, pct=pct, detail=f"Quedan {_fmt(remaining)}.", short=_fmt(remaining))


def evaluate(ticket, cal=None, now=None):
    """Estado completo del SLA de un ticket: respuesta, resolución y el resumen para mostrar en listas."""
    cal = cal or get_calendar()
    now = now or timezone.now()
    closed = ticket.status == "closed"
    # Cerrado antes de que lo atendieran: se canceló y el SLA no aplica
    cancelled = closed and ticket.resolved_at is None and ticket.assigned_at is None
    p = ticket.priority

    response = evaluate_metric(
        cal, kind="Respuesta", created=ticket.created_at, due=ticket.response_due_at,
        base=timedelta(minutes=p.response_minutes), done_at=ticket.first_response_at,
        paused_at=None, now=now, cancelled=cancelled or (closed and ticket.first_response_at is None),
    )
    resolution = evaluate_metric(
        cal, kind="Resolución", created=ticket.created_at, due=ticket.resolution_due_at,
        base=timedelta(minutes=p.resolution_minutes),
        done_at=ticket.resolved_at or (ticket.closed_at if closed and not cancelled else None),
        paused_at=ticket.sla_paused_at, now=now, cancelled=cancelled,
    )
    metrics = [response, resolution]
    headline = (
        next((m for m in metrics if m["state"] == "breached"), None)
        or next((m for m in metrics if m["state"] == "warning"), None)
        or resolution
    )
    return {"response": response, "resolution": resolution, "metrics": metrics,
            "headline": headline, "cancelled": cancelled}