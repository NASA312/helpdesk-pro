from django.db import transaction
from django.utils import timezone

from apps.sla import services as sla

from .models import Ticket, TicketAttachment, TicketComment, TicketCounter, TicketEvent

S = Ticket.Status
Kind = TicketEvent.Kind


class TicketError(Exception):
    """Una regla de negocio no se cumple. El mensaje se le muestra al usuario."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class NoteRequired(TicketError):
    """Falta la solución o el motivo. El tablero responde pidiéndolo en vez de fallar."""


def log(ticket, actor, kind, message, internal=False):
    return TicketEvent.objects.create(
        ticket=ticket, actor=actor, kind=kind, message=message[:255], is_internal=internal
    )


def _lock(ticket):
    """Vuelve a leer el ticket bloqueando su fila: evita que dos personas lo cambien a la vez."""
    return Ticket.objects.select_for_update().get(pk=ticket.pk)


def _mark_first_response(ticket, actor):
    if ticket.first_response_at is None and actor.is_support_staff and ticket.requester_id != actor.pk:
        ticket.first_response_at = timezone.now()


def _attach(ticket, comment, actor, file):
    attachment = TicketAttachment.objects.create(
        ticket=ticket, comment=comment, uploaded_by=actor,
        file=file, filename=file.name[:255], size=file.size,
    )
    log(ticket, actor, Kind.FILE, f"adjuntó «{attachment.filename}»", internal=bool(comment and comment.is_internal))
    return attachment


def _post_comment(ticket, actor, body, internal):
    comment = TicketComment.objects.create(ticket=ticket, author=actor, body=body, is_internal=internal)
    if internal:
        log(ticket, actor, Kind.NOTE, "agregó una nota interna", internal=True)
    else:
        log(ticket, actor, Kind.COMMENT, "agregó un comentario")
    return comment


# ---------------- Casos de uso ----------------

@transaction.atomic
def create_ticket(*, creator, requester, title, description, category, priority, asset=None, file=None):
    ticket = Ticket.objects.create(
        number=TicketCounter.next_number(),
        title=title.strip(), description=description.strip(),
        category=category, priority=priority, asset=asset,
        requester=requester, department=requester.department,
    )
    sla.apply_deadlines(ticket)
    ticket.save(update_fields=["response_due_at", "resolution_due_at"])

    if creator.pk == requester.pk:
        log(ticket, creator, Kind.CREATED, "creó el ticket")
    else:
        log(ticket, creator, Kind.CREATED, f"creó el ticket en nombre de {requester.display_name}")
    if file:
        _attach(ticket, None, creator, file)
    return ticket


@transaction.atomic
def assign(ticket, actor, assignee):
    ticket = _lock(ticket)
    if not ticket.user_can_assign(actor):
        raise TicketError("No puedes asignar este ticket en su estado actual.")
    if not (assignee.is_active and assignee.is_support_staff):
        raise TicketError("Solo se puede asignar a técnicos o administradores activos.")
    if ticket.assigned_to_id == assignee.pk:
        raise TicketError("El ticket ya está asignado a esa persona.")

    previous = ticket.assigned_to
    ticket.assigned_to = assignee
    ticket.assigned_at = timezone.now()
    if ticket.status == S.NEW:
        ticket.status = S.ASSIGNED
    ticket.save()

    if previous is None and assignee.pk == actor.pk:
        message = "tomó el ticket"
    elif previous is None:
        message = f"asignó el ticket a {assignee.display_name}"
    else:
        message = f"reasignó el ticket de {previous.display_name} a {assignee.display_name}"
    log(ticket, actor, Kind.ASSIGNED, message)
    return ticket


def take(ticket, actor):
    if not ticket.user_can_take(actor):
        raise TicketError("Este ticket ya no está disponible para tomarlo.")
    return assign(ticket, actor, actor)


@transaction.atomic
def change_status(ticket, actor, new_status, note=""):
    ticket = _lock(ticket)
    if new_status not in ticket.allowed_transitions(actor):
        raise TicketError("Ese cambio de estado no está permitido.")

    note = (note or "").strip()
    old = ticket.status
    reopening = old in (S.RESOLVED, S.CLOSED) and new_status in (S.IN_PROGRESS, S.NEW)
    if new_status == S.RESOLVED and not note:
        raise NoteRequired("Describe la solución aplicada.")
    if reopening and not note:
        raise NoteRequired("Explica por qué se reabre el ticket.")

    old_label = ticket.get_status_display()
    now = timezone.now()
    ticket.status = new_status
    if new_status == S.RESOLVED:
        ticket.resolved_at = now
        ticket.solution = note
    elif new_status == S.CLOSED:
        ticket.closed_at = now
    elif reopening:
        ticket.resolved_at = None
        ticket.closed_at = None

    # El reloj del SLA se detiene mientras se espera al usuario
    if new_status == S.WAITING_USER:
        sla.pause(ticket, now)
    elif old == S.WAITING_USER:
        sla.resume(ticket, now)

    _mark_first_response(ticket, actor)
    ticket.save()

    if new_status == S.RESOLVED:
        message = "marcó el ticket como resuelto"
    elif new_status == S.CLOSED:
        message = "cerró el ticket"
    elif reopening:
        message = "reabrió el ticket"
    else:
        message = f"cambió el estado de «{old_label}» a «{Ticket.Status(new_status).label}»"
    log(ticket, actor, Kind.STATUS, message)

    if note and new_status != S.RESOLVED:         # al resolver, la nota ya es la solución
        _post_comment(ticket, actor, note, internal=False)
    return ticket


@transaction.atomic
def add_comment(ticket, actor, body, *, internal=False, file=None):
    ticket = _lock(ticket)
    if not ticket.user_can_comment(actor):
        raise TicketError("No puedes comentar en este ticket.")
    if internal and not ticket.user_can_see_internal(actor):
        raise TicketError("Solo el equipo que atiende el ticket puede escribir notas internas.")

    comment = _post_comment(ticket, actor, body.strip(), internal)
    if file:
        _attach(ticket, comment, actor, file)
    if not internal:
        _mark_first_response(ticket, actor)
        if ticket.status == S.WAITING_USER and ticket.requester_id == actor.pk:
            ticket.status = S.IN_PROGRESS
            sla.resume(ticket, timezone.now())
            log(ticket, actor, Kind.STATUS, "respondió y el ticket volvió a «En proceso»")
    ticket.save()
    return comment


@transaction.atomic
def update_details(ticket, actor, *, category, priority, asset):
    """Cambia categoría, prioridad y equipo. Devuelve cuántos campos cambiaron."""
    ticket = _lock(ticket)
    if not ticket.user_can_work(actor) or ticket.status == S.CLOSED:
        raise TicketError("No puedes editar este ticket.")

    changes = 0
    if ticket.priority_id != priority.pk:
        recalculated = ticket.resolved_at is None
        suffix = " (plazos del SLA recalculados)" if recalculated else ""
        log(ticket, actor, Kind.UPDATED,
            f"cambió la prioridad de «{ticket.priority.name}» a «{priority.name}»{suffix}")
        ticket.priority = priority
        if recalculated:
            sla.apply_deadlines(ticket)
        changes += 1
    if ticket.category_id != category.pk:
        log(ticket, actor, Kind.UPDATED, f"cambió la categoría de «{ticket.category.name}» a «{category.name}»")
        ticket.category = category
        changes += 1
    if ticket.asset_id != (asset.pk if asset else None):
        old = ticket.asset.code if ticket.asset else "ninguno"
        log(ticket, actor, Kind.UPDATED, f"cambió el equipo de «{old}» a «{asset.code if asset else 'ninguno'}»")
        ticket.asset = asset
        changes += 1
    if changes:
        ticket.save()
    return changes


def board_move(ticket, actor, target, note=""):
    """Movimiento desde el tablero Kanban. Reutiliza las reglas de negocio de siempre."""
    if target not in Ticket.Status.values:
        raise TicketError("Estado no válido.")
    if target == ticket.status:
        return ticket
    if ticket.status == S.NEW:
        if target == S.ASSIGNED:
            return take(ticket, actor)                       # arrastrar a "Asignado" = tomar el ticket
        raise TicketError("Toma el ticket primero: arrástralo a la columna «Asignado».")
    return change_status(ticket, actor, target, note)