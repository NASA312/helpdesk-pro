from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Priority
from apps.sla.models import BusinessSchedule
from apps.sla.services import apply_deadlines

from .models import Ticket
from .services import assign, change_status, create_ticket, take, update_details

pytestmark = pytest.mark.django_db
S = Ticket.Status


def make_ticket(usuario, categoria, prioridad, title="Otro ticket"):
    return create_ticket(
        creator=usuario, requester=usuario, title=title, description="Detalle",
        category=categoria, priority=prioridad,
    )


def set_24x7():
    schedule = BusinessSchedule.get()
    schedule.is_24x7 = True
    schedule.save()


def move(client, ticket, status, note=None):
    data = {"status": status}
    if note:
        data["note"] = note
    return client.post(reverse("ticket_board_move", args=[ticket.pk]), data)


# ---------- Plazos ----------

def test_un_ticket_nuevo_nace_con_plazos(ticket):
    assert ticket.response_due_at and ticket.resolution_due_at
    assert ticket.response_due_at < ticket.resolution_due_at
    assert ticket.sla_paused_at is None and ticket.sla_paused_seconds == 0


def test_plazos_exactos_en_modo_24x7(ticket):
    set_24x7()
    apply_deadlines(ticket)
    assert ticket.response_due_at == ticket.created_at + timedelta(minutes=30)
    assert ticket.resolution_due_at == ticket.created_at + timedelta(minutes=240)


def test_cambiar_la_prioridad_recalcula_el_sla(tecnico, ticket, categoria):
    set_24x7()
    take(ticket, tecnico)
    critica = Priority.objects.get(level=4)
    update_details(ticket, tecnico, category=categoria, priority=critica, asset=None)
    ticket.refresh_from_db()
    assert ticket.resolution_due_at == ticket.created_at + timedelta(minutes=120)
    assert ticket.events.filter(message__contains="SLA").exists()


def test_esperando_usuario_pausa_y_responder_reanuda(client, tecnico, usuario, ticket):
    set_24x7()
    take(ticket, tecnico)
    change_status(ticket, tecnico, S.IN_PROGRESS)
    change_status(ticket, tecnico, S.WAITING_USER, "¿Puedes enviar una foto?")
    ticket.refresh_from_db()
    assert ticket.sla_paused_at is not None

    Ticket.objects.filter(pk=ticket.pk).update(sla_paused_at=timezone.now() - timedelta(hours=2))
    client.force_login(usuario)
    client.post(reverse("ticket_comment", args=[ticket.pk]), {"body": "Aquí está"})
    ticket.refresh_from_db()
    assert ticket.status == S.IN_PROGRESS and ticket.sla_paused_at is None
    assert 7190 <= ticket.sla_paused_seconds <= 7300
    assert ticket.resolution_due_at == ticket.created_at + timedelta(minutes=240, seconds=ticket.sla_paused_seconds)


def test_salir_de_esperando_usuario_por_cualquier_via_reanuda(tecnico, ticket):
    take(ticket, tecnico)
    change_status(ticket, tecnico, S.WAITING_USER)
    change_status(ticket, tecnico, S.RESOLVED, "Se resolvió")
    ticket.refresh_from_db()
    assert ticket.sla_paused_at is None


# ---------- Filtro, panel y SLA visible ----------

def test_filtro_sla_incumplido(client, administrador, usuario, ticket, categoria, prioridad):
    en_tiempo = make_ticket(usuario, categoria, prioridad)
    Ticket.objects.filter(pk=ticket.pk).update(response_due_at=timezone.now() - timedelta(hours=1))
    client.force_login(administrador)
    html = client.get(reverse("ticket_list"), {"sla": "breached"}).content.decode()
    assert ticket.code in html and en_tiempo.code not in html


def test_un_ticket_en_pausa_no_cuenta_como_incumplido(client, administrador, ticket):
    past = timezone.now() - timedelta(hours=3)
    Ticket.objects.filter(pk=ticket.pk).update(
        status=S.WAITING_USER, first_response_at=past,
        resolution_due_at=past + timedelta(hours=1), sla_paused_at=past,
    )
    client.force_login(administrador)
    assert ticket.code not in client.get(reverse("ticket_list"), {"sla": "breached"}).content.decode()


def test_panel_sla_segun_el_rol(client, tecnico, usuario, otro_usuario, ticket):
    take(ticket, tecnico)
    url = reverse("ticket_sla", args=[ticket.pk])
    client.force_login(tecnico)
    html = client.get(url).content.decode()
    assert "Respuesta" in html and "Resolución" in html
    client.force_login(usuario)
    html = client.get(url).content.decode()
    assert "Resolución estimada" in html and "Respuesta" not in html
    client.force_login(otro_usuario)
    assert client.get(url).status_code == 404


def test_el_listado_muestra_la_columna_sla_solo_al_soporte(client, tecnico, usuario, ticket):
    client.force_login(tecnico)
    assert ">SLA</th>" in client.get(reverse("ticket_list")).content.decode()
    client.force_login(usuario)
    assert ">SLA</th>" not in client.get(reverse("ticket_list")).content.decode()


def test_el_panel_cuenta_los_tickets_con_sla_incumplido(client, tecnico, ticket):
    Ticket.objects.filter(pk=ticket.pk).update(response_due_at=timezone.now() - timedelta(minutes=5))
    client.force_login(tecnico)
    assert client.get(reverse("dashboard")).context["tickets_breached"] == 1


# ---------- Tablero ----------

def test_el_usuario_no_accede_al_tablero(client, usuario):
    client.force_login(usuario)
    assert client.get(reverse("ticket_board")).status_code == 403


def test_el_tablero_muestra_la_cola_y_los_tickets_propios(client, tecnico, tecnico2, administrador, usuario, ticket, categoria, prioridad):
    ajeno = make_ticket(usuario, categoria, prioridad, "De otro técnico")
    assign(ajeno, administrador, tecnico2)
    client.force_login(tecnico)
    html = client.get(reverse("ticket_board")).content.decode()
    assert ticket.code in html and ajeno.code not in html


def test_los_cerrados_antiguos_no_aparecen(client, administrador, usuario, ticket, categoria, prioridad):
    reciente = make_ticket(usuario, categoria, prioridad)
    now = timezone.now()
    Ticket.objects.filter(pk=ticket.pk).update(status=S.CLOSED, closed_at=now - timedelta(days=10))
    Ticket.objects.filter(pk=reciente.pk).update(status=S.CLOSED, closed_at=now - timedelta(days=1))
    client.force_login(administrador)
    html = client.get(reverse("ticket_board")).content.decode()
    assert reciente.code in html and ticket.code not in html


def test_arrastrar_a_asignado_toma_el_ticket(client, tecnico, ticket):
    client.force_login(tecnico)
    response = move(client, ticket, "assigned")
    assert response.status_code == 200 and response.json()["ok"] is True
    assert ticket.code in response.json()["html"]
    ticket.refresh_from_db()
    assert ticket.assigned_to == tecnico and ticket.status == S.ASSIGNED


def test_no_se_puede_saltar_de_nuevo_a_en_proceso(client, tecnico, ticket):
    client.force_login(tecnico)
    response = move(client, ticket, "in_progress")
    assert response.status_code == 409 and "Toma el ticket" in response.json()["error"]
    ticket.refresh_from_db()
    assert ticket.status == S.NEW


def test_resolver_desde_el_tablero_pide_la_solucion(client, tecnico, ticket):
    take(ticket, tecnico)
    client.force_login(tecnico)
    response = move(client, ticket, "resolved")
    assert response.status_code == 422 and response.json()["needs_note"] is True
    ticket.refresh_from_db()
    assert ticket.status == S.ASSIGNED

    assert move(client, ticket, "resolved", "Se reinició el router").status_code == 200
    ticket.refresh_from_db()
    assert ticket.status == S.RESOLVED and ticket.solution == "Se reinició el router"


def test_movimientos_no_permitidos_por_el_tablero(client, tecnico, ticket):
    take(ticket, tecnico)
    client.force_login(tecnico)
    assert move(client, ticket, "closed").status_code == 409          # el técnico no cierra desde "Asignado"
    assert move(client, ticket, "nonsense").status_code == 409
    assert move(client, ticket, "new").status_code == 409


def test_el_usuario_no_puede_mover_tarjetas(client, usuario, ticket):
    client.force_login(usuario)
    assert move(client, ticket, "assigned").status_code == 403
    ticket.refresh_from_db()
    assert ticket.status == S.NEW


def test_un_tecnico_no_mueve_tickets_de_otro(client, tecnico, tecnico2, administrador, ticket):
    assign(ticket, administrador, tecnico2)
    client.force_login(tecnico)
    assert move(client, ticket, "in_progress").status_code == 404


def test_el_administrador_mueve_el_ticket_de_un_tecnico(client, tecnico, administrador, ticket):
    take(ticket, tecnico)
    client.force_login(administrador)
    assert move(client, ticket, "in_progress").status_code == 200
    ticket.refresh_from_db()
    assert ticket.status == S.IN_PROGRESS


def test_el_tablero_filtra_por_prioridad(client, administrador, usuario, ticket, categoria):
    baja = Priority.objects.get(level=1)
    otro = make_ticket(usuario, categoria, baja, "Poco urgente")
    client.force_login(administrador)
    html = client.get(reverse("ticket_board"), {"priority": baja.pk}).content.decode()
    assert otro.code in html and ticket.code not in html