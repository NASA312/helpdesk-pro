from io import StringIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from apps.assets.models import Asset
from apps.catalog.models import Category, Priority

from .models import Ticket, TicketComment
from .services import TicketError, add_comment, assign, change_status, create_ticket, take

pytestmark = pytest.mark.django_db
S = Ticket.Status


def new_data(categoria, prioridad, **override):
    data = {
        "title": "Mi PC no enciende", "description": "Ayer dejó de prender",
        "category": categoria.pk, "priority": prioridad.pk, "asset": "",
    }
    data.update(override)
    return data


def url(name, ticket, *extra):
    return reverse(name, args=[ticket.pk, *extra])


def make_ticket(usuario, categoria, prioridad, title="Otro ticket", **extra):
    return create_ticket(
        creator=usuario, requester=usuario, title=title, description="Detalle",
        category=categoria, priority=prioridad, **extra,
    )


# ---------- Numeración y creación ----------

def test_codigo_con_formato():
    assert Ticket(number=184).code == "TK-000184"


def test_numeracion_consecutiva(usuario, categoria, prioridad):
    numbers = [make_ticket(usuario, categoria, prioridad).number for _ in range(3)]
    assert numbers == [1, 2, 3]


def test_usuario_crea_ticket_con_foto(client, usuario, depto, categoria, prioridad):
    usuario.department = depto
    usuario.save()
    client.force_login(usuario)
    foto = SimpleUploadedFile("foto.png", b"\x89PNG-falso", content_type="image/png")
    response = client.post(reverse("ticket_create"), new_data(categoria, prioridad, file=foto))
    t = Ticket.objects.get()
    assert response.status_code == 302 and response.url == t.get_absolute_url()
    assert t.requester == usuario and t.status == S.NEW and t.department == depto and t.number == 1
    assert t.events.filter(kind="created").exists()
    assert t.attachments.get().filename == "foto.png"


def test_usuario_no_puede_elegir_solicitante(client, usuario, otro_usuario, categoria, prioridad):
    client.force_login(usuario)
    client.post(reverse("ticket_create"), new_data(categoria, prioridad, requester=otro_usuario.pk))
    assert Ticket.objects.get().requester == usuario


def test_personal_crea_en_nombre_de_otra_persona(client, tecnico, usuario, categoria, prioridad):
    client.force_login(tecnico)
    client.post(reverse("ticket_create"), new_data(categoria, prioridad, requester=usuario.pk))
    t = Ticket.objects.get()
    assert t.requester == usuario
    assert "en nombre de" in t.events.get(kind="created").message


def test_el_usuario_solo_elige_sus_equipos(client, usuario, otro_usuario, categoria, prioridad):
    ajeno = Asset.objects.create(code="PC-X", assigned_to=otro_usuario)
    propio = Asset.objects.create(code="PC-Y", assigned_to=usuario)
    client.force_login(usuario)
    assert client.post(reverse("ticket_create"), new_data(categoria, prioridad, asset=ajeno.pk)).status_code == 200
    assert not Ticket.objects.exists()
    assert client.post(reverse("ticket_create"), new_data(categoria, prioridad, asset=propio.pk)).status_code == 302
    assert Ticket.objects.get().asset == propio


def test_categoria_inactiva_se_rechaza(client, usuario, categoria, prioridad):
    categoria.is_active = False
    categoria.save()
    client.force_login(usuario)
    assert client.post(reverse("ticket_create"), new_data(categoria, prioridad)).status_code == 200
    assert not Ticket.objects.exists()


def test_adjunto_ejecutable_se_rechaza(client, usuario, categoria, prioridad):
    client.force_login(usuario)
    exe = SimpleUploadedFile("virus.exe", b"MZ")
    assert client.post(reverse("ticket_create"), new_data(categoria, prioridad, file=exe)).status_code == 200
    assert not Ticket.objects.exists()


# ---------- Quién ve qué ----------

def test_anonimo_es_redirigido_al_login(client, ticket):
    for name, args in (("ticket_list", []), ("ticket_detail", [ticket.pk]), ("ticket_create", [])):
        response = client.get(reverse(name, args=args))
        assert response.status_code == 302 and response.url.startswith(reverse("login"))


def test_usuario_solo_ve_sus_tickets(client, usuario, otro_usuario, ticket, categoria, prioridad):
    ajeno = make_ticket(otro_usuario, categoria, prioridad)
    client.force_login(usuario)
    html = client.get(reverse("ticket_list")).content.decode()
    assert ticket.code in html and ajeno.code not in html
    assert client.get(ajeno.get_absolute_url()).status_code == 404


def test_tecnico_ve_los_suyos_y_la_cola_pero_no_los_de_otros(
    client, tecnico, tecnico2, administrador, usuario, ticket, categoria, prioridad
):
    de_otro = make_ticket(usuario, categoria, prioridad, "De otro técnico")
    assign(de_otro, administrador, tecnico2)
    client.force_login(tecnico)
    html = client.get(reverse("ticket_list")).content.decode()
    assert ticket.code in html and de_otro.code not in html
    assert client.get(de_otro.get_absolute_url()).status_code == 404


def test_administrador_ve_todos(client, administrador, tecnico2, usuario, ticket, categoria, prioridad):
    asignado = make_ticket(usuario, categoria, prioridad)
    assign(asignado, administrador, tecnico2)
    client.force_login(administrador)
    html = client.get(reverse("ticket_list")).content.decode()
    assert ticket.code in html and asignado.code in html


# ---------- Tomar y asignar ----------

def test_tecnico_toma_un_ticket(client, tecnico, ticket):
    client.force_login(tecnico)
    assert client.post(url("ticket_take", ticket)).status_code == 302
    ticket.refresh_from_db()
    assert ticket.assigned_to == tecnico and ticket.status == S.ASSIGNED and ticket.assigned_at is not None
    assert ticket.events.filter(message="tomó el ticket").exists()


def test_otro_tecnico_no_puede_tomar_uno_ya_tomado(client, tecnico, tecnico2, ticket):
    take(ticket, tecnico)
    client.force_login(tecnico2)
    assert client.post(url("ticket_take", ticket)).status_code == 404
    ticket.refresh_from_db()
    assert ticket.assigned_to == tecnico


def test_usuario_no_puede_tomar_ni_asignar(client, usuario, tecnico, ticket):
    client.force_login(usuario)
    client.post(url("ticket_take", ticket))
    client.post(url("ticket_assign", ticket), {"assignee": tecnico.pk})
    ticket.refresh_from_db()
    assert ticket.assigned_to is None and ticket.status == S.NEW


def test_administrador_asigna_y_reasigna_sin_perder_el_estado(client, administrador, tecnico, tecnico2, ticket):
    client.force_login(administrador)
    client.post(url("ticket_assign", ticket), {"assignee": tecnico.pk})
    ticket.refresh_from_db()
    assert ticket.assigned_to == tecnico and ticket.status == S.ASSIGNED

    change_status(ticket, tecnico, S.IN_PROGRESS)
    client.post(url("ticket_assign", ticket), {"assignee": tecnico2.pk})
    ticket.refresh_from_db()
    assert ticket.assigned_to == tecnico2 and ticket.status == S.IN_PROGRESS
    assert ticket.events.filter(message__startswith="reasignó").exists()


def test_tecnico_reasigna_su_ticket_y_pierde_el_acceso(client, tecnico, tecnico2, ticket):
    take(ticket, tecnico)
    client.force_login(tecnico)
    response = client.post(url("ticket_assign", ticket), {"assignee": tecnico2.pk})
    assert response.status_code == 302 and response.url == reverse("ticket_list")
    ticket.refresh_from_db()
    assert ticket.assigned_to == tecnico2


def test_no_se_asigna_a_usuarios_normales_ni_inactivos(client, administrador, usuario, tecnico, ticket):
    client.force_login(administrador)
    client.post(url("ticket_assign", ticket), {"assignee": usuario.pk})
    tecnico.is_active = False
    tecnico.save()
    client.post(url("ticket_assign", ticket), {"assignee": tecnico.pk})
    ticket.refresh_from_db()
    assert ticket.assigned_to is None


# ---------- Estados ----------

def test_flujo_completo_de_un_ticket(client, tecnico, usuario, ticket):
    take(ticket, tecnico)
    change_status(ticket, tecnico, S.IN_PROGRESS)
    change_status(ticket, tecnico, S.WAITING_USER, "¿Qué mensaje ves?")
    ticket.refresh_from_db()
    assert ticket.status == S.WAITING_USER and ticket.first_response_at is not None

    client.force_login(usuario)                     # al responder, vuelve a "En proceso"
    client.post(url("ticket_comment", ticket), {"body": "Dice sin red"})
    ticket.refresh_from_db()
    assert ticket.status == S.IN_PROGRESS

    change_status(ticket, tecnico, S.RESOLVED, "Se reinició el adaptador de red")
    ticket.refresh_from_db()
    assert ticket.status == S.RESOLVED and ticket.solution and ticket.resolved_at is not None

    client.post(url("ticket_status", ticket), {"status": "closed", "note": ""})
    ticket.refresh_from_db()
    assert ticket.status == S.CLOSED and ticket.closed_at is not None


def test_resolver_exige_solucion(tecnico, ticket):
    take(ticket, tecnico)
    with pytest.raises(TicketError):
        change_status(ticket, tecnico, S.RESOLVED, "")


def test_transiciones_no_permitidas(client, tecnico, usuario, ticket, categoria, prioridad):
    take(ticket, tecnico)
    with pytest.raises(TicketError):
        change_status(ticket, tecnico, S.CLOSED)             # el técnico no salta de Asignado a Cerrado
    with pytest.raises(TicketError):
        change_status(ticket, usuario, S.IN_PROGRESS)        # el usuario no lo pone en proceso
    sin_tomar = make_ticket(usuario, categoria, prioridad)
    with pytest.raises(TicketError):
        change_status(sin_tomar, tecnico, S.IN_PROGRESS)     # hay que tomarlo primero
    client.force_login(tecnico)
    client.post(url("ticket_status", ticket), {"status": "closed", "note": ""})
    ticket.refresh_from_db()
    assert ticket.status == S.ASSIGNED


def test_usuario_reabre_un_ticket_resuelto_solo_con_motivo(client, tecnico, usuario, ticket):
    take(ticket, tecnico)
    change_status(ticket, tecnico, S.RESOLVED, "Se cambió el cable")
    client.force_login(usuario)
    client.post(url("ticket_status", ticket), {"status": "in_progress", "note": ""})
    ticket.refresh_from_db()
    assert ticket.status == S.RESOLVED

    client.post(url("ticket_status", ticket), {"status": "in_progress", "note": "Sigue sin conexión"})
    ticket.refresh_from_db()
    assert ticket.status == S.IN_PROGRESS and ticket.resolved_at is None
    assert ticket.comments.filter(body="Sigue sin conexión").exists()


def test_usuario_cancela_un_ticket_nuevo_y_sale_de_la_cola(client, usuario, tecnico, ticket):
    client.force_login(usuario)
    client.post(url("ticket_status", ticket), {"status": "closed", "note": ""})
    ticket.refresh_from_db()
    assert ticket.status == S.CLOSED and ticket.assigned_to is None
    client.force_login(tecnico)
    assert client.get(ticket.get_absolute_url()).status_code == 404


def test_ticket_cerrado_no_admite_comentarios_y_el_admin_puede_reabrirlo(administrador, usuario, ticket):
    change_status(ticket, usuario, S.CLOSED)
    with pytest.raises(TicketError):
        add_comment(ticket, usuario, "hola")
    change_status(ticket, administrador, S.NEW, "Se cerró por error")
    ticket.refresh_from_db()
    assert ticket.status == S.NEW and ticket.closed_at is None


# ---------- Comentarios y notas internas ----------

def test_notas_internas_solo_las_ve_el_equipo(client, tecnico, usuario, ticket):
    take(ticket, tecnico)
    add_comment(ticket, tecnico, "Nota secreta técnica", internal=True)
    add_comment(ticket, tecnico, "Mensaje público")

    client.force_login(usuario)
    html = client.get(ticket.get_absolute_url()).content.decode()
    assert "Mensaje público" in html
    assert "Nota secreta técnica" not in html and "agregó una nota interna" not in html

    client.force_login(tecnico)
    html = client.get(ticket.get_absolute_url()).content.decode()
    assert "Nota secreta técnica" in html and "agregó una nota interna" in html


def test_usuario_no_puede_publicar_notas_internas(client, usuario, ticket):
    client.force_login(usuario)
    client.post(url("ticket_comment", ticket), {"body": "Intento", "is_internal": "on"})
    assert TicketComment.objects.get().is_internal is False
    with pytest.raises(TicketError):
        add_comment(ticket, usuario, "Intento", internal=True)


def test_tecnico_sin_tomar_el_ticket_no_puede_comentar(client, tecnico, ticket):
    client.force_login(tecnico)
    client.post(url("ticket_comment", ticket), {"body": "Hola"})
    assert not TicketComment.objects.exists()


def test_primera_respuesta_solo_cuenta_la_publica_del_soporte(tecnico, usuario, ticket):
    take(ticket, tecnico)
    add_comment(ticket, usuario, "Gracias")
    add_comment(ticket, tecnico, "Nota", internal=True)
    ticket.refresh_from_db()
    assert ticket.first_response_at is None
    add_comment(ticket, tecnico, "Estoy revisando")
    ticket.refresh_from_db()
    assert ticket.first_response_at is not None


# ---------- Adjuntos protegidos ----------

def test_adjuntos_de_notas_internas_estan_protegidos(client, tecnico, usuario, otro_usuario, ticket):
    take(ticket, tecnico)
    interna = add_comment(
        ticket, tecnico, "ver log", internal=True, file=SimpleUploadedFile("log.txt", b"datos")
    ).attachments.get()
    publica = add_comment(
        ticket, tecnico, "manual", file=SimpleUploadedFile("guia.txt", b"pasos")
    ).attachments.get()

    client.force_login(tecnico)
    response = client.get(url("ticket_attachment", ticket, interna.pk))
    assert response.status_code == 200 and b"".join(response.streaming_content) == b"datos"

    client.force_login(usuario)
    assert client.get(url("ticket_attachment", ticket, interna.pk)).status_code == 404
    assert client.get(url("ticket_attachment", ticket, publica.pk)).status_code == 200

    client.force_login(otro_usuario)
    assert client.get(url("ticket_attachment", ticket, publica.pk)).status_code == 404


# ---------- Editar detalles y eliminar ----------

def test_tecnico_cambia_la_prioridad_y_queda_en_el_historial(client, tecnico, ticket, categoria):
    take(ticket, tecnico)
    critica = Priority.objects.get(level=4)
    client.force_login(tecnico)
    response = client.post(url("ticket_edit", ticket), {"category": categoria.pk, "priority": critica.pk, "asset": ""})
    assert response.status_code == 302
    ticket.refresh_from_db()
    assert ticket.priority == critica
    assert ticket.events.filter(message__contains="prioridad").exists()


def test_usuario_no_puede_editar_los_detalles(client, usuario, ticket):
    client.force_login(usuario)
    assert client.get(url("ticket_edit", ticket)).status_code == 403


def test_solo_el_administrador_elimina(client, tecnico, administrador, ticket):
    client.force_login(tecnico)
    assert client.post(url("ticket_delete", ticket)).status_code == 403
    client.force_login(administrador)
    assert client.post(url("ticket_delete", ticket)).status_code == 302
    ticket.refresh_from_db()
    assert ticket.deleted_at is not None
    assert client.get(ticket.get_absolute_url()).status_code == 404
    assert ticket.code not in client.get(reverse("ticket_list")).content.decode()


def test_una_categoria_con_tickets_no_se_elimina(client, administrador, ticket, categoria):
    client.force_login(administrador)
    assert client.post(reverse("category_delete", args=[categoria.pk])).status_code == 302
    assert Category.objects.filter(pk=categoria.pk).exists()


# ---------- Búsqueda y filtros ----------

def test_busqueda_por_codigo_y_filtros(client, administrador, tecnico, usuario, ticket, categoria):
    baja = Priority.objects.get(level=1)
    otro = make_ticket(usuario, Category.objects.get(name="Impresoras"), baja, "Impresora atascada")
    client.force_login(administrador)

    html = client.get(reverse("ticket_list"), {"q": "TK-000002"}).content.decode()
    assert otro.code in html and ticket.code not in html
    html = client.get(reverse("ticket_list"), {"priority": baja.pk}).content.decode()
    assert otro.code in html and ticket.code not in html
    html = client.get(reverse("ticket_list"), {"assigned": "none", "status": "new"}).content.decode()
    assert otro.code in html and ticket.code in html

    take(ticket, tecnico)
    html = client.get(reverse("ticket_list"), {"assigned": tecnico.pk}).content.decode()
    assert ticket.code in html and otro.code not in html
    assert client.get(reverse("ticket_list"), {"q": "99999999999999"}).status_code == 200


# ---------- Equipo y panel ----------

def test_el_detalle_del_equipo_muestra_sus_tickets(client, tecnico, usuario, categoria, prioridad):
    equipo = Asset.objects.create(code="PC-T-1", assigned_to=usuario)
    t = make_ticket(usuario, categoria, prioridad, asset=equipo)
    for person in (tecnico, usuario):
        client.force_login(person)
        assert t.code in client.get(equipo.get_absolute_url()).content.decode()


def test_el_panel_cuenta_los_tickets_sin_asignar(client, tecnico, ticket):
    client.force_login(tecnico)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert response.context["tickets_unassigned"] == 1 and response.context["tickets_open"] == 1


# ---------- Datos demo ----------

def test_seed_tickets_crea_tickets_y_no_duplica(settings):
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_tickets", stdout=StringIO())
    call_command("seed_tickets", stdout=StringIO())
    assert Ticket.objects.count() == 5
    assert Ticket.objects.filter(status=S.RESOLVED).count() == 1