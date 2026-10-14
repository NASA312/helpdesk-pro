from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from conftest import make_user

from .models import Asset, AssetAssignment
from .services import sync_assignment

pytestmark = pytest.mark.django_db


def asset_data(**override):
    data = {
        "code": "PC-NEW-001", "asset_type": "computer", "brand": "Dell", "model": "OptiPlex",
        "serial_number": "", "ip_address": "", "operating_system": "", "status": "active",
        "assigned_to": "", "department": "", "purchase_date": "", "warranty_until": "", "notes": "",
    }
    data.update(override)
    return data


# ---------- Permisos ----------

def test_anonimo_es_redirigido_al_login(client, equipo):
    for name, args in (("asset_list", []), ("asset_detail", [equipo.pk]), ("my_assets", [])):
        response = client.get(reverse(name, args=args))
        assert response.status_code == 302 and response.url.startswith(reverse("login"))


@pytest.mark.parametrize("name", ["asset_list", "asset_create"])
def test_usuario_no_gestiona_el_inventario(client, usuario, name):
    client.force_login(usuario)
    assert client.get(reverse(name)).status_code == 403


def test_tecnico_y_administrador_ven_el_inventario(client, tecnico, administrador, equipo):
    for person in (tecnico, administrador):
        client.force_login(person)
        assert equipo.code in client.get(reverse("asset_list")).content.decode()


def test_usuario_no_puede_editar_ni_eliminar(client, usuario, equipo):
    client.force_login(usuario)
    assert client.get(reverse("asset_update", args=[equipo.pk])).status_code == 403
    assert client.post(reverse("asset_delete", args=[equipo.pk])).status_code == 403


def test_tecnico_edita_pero_no_elimina(client, tecnico, equipo):
    client.force_login(tecnico)
    assert client.get(reverse("asset_update", args=[equipo.pk])).status_code == 200
    assert client.post(reverse("asset_delete", args=[equipo.pk])).status_code == 403
    html = client.get(reverse("asset_detail", args=[equipo.pk])).content.decode()
    assert "Eliminar" not in html


# ---------- Alta y validaciones ----------

def test_el_codigo_se_guarda_en_mayusculas(client, tecnico):
    client.force_login(tecnico)
    assert client.post(reverse("asset_create"), asset_data(code="pc-new-001")).status_code == 302
    assert Asset.objects.get().code == "PC-NEW-001"


def test_codigo_repetido_se_rechaza_sin_importar_mayusculas(client, tecnico, equipo):
    client.force_login(tecnico)
    assert client.post(reverse("asset_create"), asset_data(code="pc-rh-023")).status_code == 200
    assert Asset.objects.count() == 1


def test_un_equipo_eliminado_libera_su_codigo(client, tecnico, equipo):
    equipo.soft_delete()
    client.force_login(tecnico)
    assert client.post(reverse("asset_create"), asset_data(code="PC-RH-023")).status_code == 302
    assert Asset.objects.alive().filter(code="PC-RH-023").count() == 1
    assert Asset.objects.count() == 2


def test_numero_de_serie_repetido_se_rechaza(client, tecnico, equipo):
    Asset.objects.filter(pk=equipo.pk).update(serial_number="SN-1")
    client.force_login(tecnico)
    assert client.post(reverse("asset_create"), asset_data(serial_number="SN-1")).status_code == 200
    assert not Asset.objects.filter(code="PC-NEW-001").exists()


@pytest.mark.parametrize("override", [
    {"ip_address": "999.1.1.1"},
    {"code": "PC RH 1"},
    {"purchase_date": "2025-05-01", "warranty_until": "2025-01-01"},
])
def test_datos_invalidos_se_rechazan(client, tecnico, override):
    client.force_login(tecnico)
    assert client.post(reverse("asset_create"), asset_data(**override)).status_code == 200
    assert not Asset.objects.exists()


def test_estado_de_la_garantia():
    hoy = timezone.localdate()
    assert Asset(warranty_until=None).warranty_state is None
    assert Asset(warranty_until=hoy - timedelta(days=1)).warranty_state == "expired"
    assert Asset(warranty_until=hoy + timedelta(days=10)).warranty_state == "expiring"
    assert Asset(warranty_until=hoy + timedelta(days=100)).warranty_state == "valid"


# ---------- Asignación e historial ----------

def test_asignar_crea_historial(client, tecnico, equipo, usuario):
    client.force_login(tecnico)
    response = client.post(
        reverse("asset_update", args=[equipo.pk]), asset_data(code=equipo.code, assigned_to=usuario.pk)
    )
    assert response.status_code == 302
    equipo.refresh_from_db()
    assert equipo.assigned_to == usuario
    a = equipo.assignments.get()
    assert a.user == usuario and a.assigned_by == tecnico and a.returned_at is None


def test_reasignar_cierra_la_anterior_y_abre_una_nueva(client, tecnico, equipo, usuario):
    otro = make_user("otro", "user")
    client.force_login(tecnico)
    url = reverse("asset_update", args=[equipo.pk])
    client.post(url, asset_data(code=equipo.code, assigned_to=usuario.pk))
    client.post(url, asset_data(code=equipo.code, assigned_to=otro.pk))
    assert equipo.assignments.count() == 2
    assert equipo.assignments.get(returned_at__isnull=True).user == otro
    assert equipo.assignments.get(user=usuario).returned_at is not None


def test_guardar_sin_cambiar_la_persona_no_duplica_historial(client, tecnico, equipo, usuario):
    client.force_login(tecnico)
    url = reverse("asset_update", args=[equipo.pk])
    client.post(url, asset_data(code=equipo.code, assigned_to=usuario.pk))
    client.post(url, asset_data(code=equipo.code, assigned_to=usuario.pk, notes="Cambió una nota"))
    assert equipo.assignments.count() == 1


def test_quitar_la_asignacion_cierra_el_historial(client, tecnico, equipo, usuario):
    equipo.assigned_to = usuario
    equipo.save()
    sync_assignment(equipo, None, tecnico)
    client.force_login(tecnico)
    client.post(reverse("asset_update", args=[equipo.pk]), asset_data(code=equipo.code, assigned_to=""))
    equipo.refresh_from_db()
    assert equipo.assigned_to is None
    assert not equipo.assignments.filter(returned_at__isnull=True).exists()
    assert equipo.assignments.count() == 1


def test_crear_con_persona_abre_asignacion_y_hereda_su_departamento(client, tecnico, depto):
    ana = make_user("ana", "user", department=depto)
    client.force_login(tecnico)
    assert client.post(reverse("asset_create"), asset_data(assigned_to=ana.pk)).status_code == 302
    asset = Asset.objects.get()
    assert asset.department == depto
    assert asset.assignments.get().user == ana


def test_equipo_dado_de_baja_no_puede_estar_asignado(client, tecnico, equipo, usuario):
    client.force_login(tecnico)
    response = client.post(
        reverse("asset_update", args=[equipo.pk]),
        asset_data(code=equipo.code, status="retired", assigned_to=usuario.pk),
    )
    assert response.status_code == 200
    equipo.refresh_from_db()
    assert equipo.status == Asset.Status.ACTIVE


def test_no_se_asigna_a_usuarios_inactivos(client, tecnico, equipo, usuario):
    usuario.is_active = False
    usuario.save()
    client.force_login(tecnico)
    response = client.post(
        reverse("asset_update", args=[equipo.pk]), asset_data(code=equipo.code, assigned_to=usuario.pk)
    )
    assert response.status_code == 200
    assert not equipo.assignments.exists()


def test_solo_una_asignacion_abierta_por_equipo(equipo, usuario):
    AssetAssignment.objects.create(asset=equipo, user=usuario)
    with pytest.raises(IntegrityError), transaction.atomic():
        AssetAssignment.objects.create(asset=equipo, user=usuario)


# ---------- Eliminación (soft delete) ----------

def test_administrador_elimina_y_conserva_el_historial(client, administrador, equipo, usuario):
    equipo.assigned_to = usuario
    equipo.save()
    sync_assignment(equipo, None, administrador)
    client.force_login(administrador)
    assert client.post(reverse("asset_delete", args=[equipo.pk])).status_code == 302

    equipo.refresh_from_db()
    assert equipo.deleted_at is not None and equipo.assigned_to is None
    assert not Asset.objects.alive().filter(pk=equipo.pk).exists()
    assert equipo.assignments.count() == 1 and not equipo.assignments.filter(returned_at__isnull=True).exists()
    assert client.get(reverse("asset_detail", args=[equipo.pk])).status_code == 404
    assert equipo.code not in client.get(reverse("asset_list")).content.decode()


# ---------- Lo que ve cada persona ----------

def test_usuario_solo_ve_sus_equipos(client, usuario, equipo):
    otro = Asset.objects.create(code="PC-OTRO-1", brand="HP")
    Asset.objects.filter(pk=equipo.pk).update(assigned_to=usuario)
    client.force_login(usuario)
    html = client.get(reverse("my_assets")).content.decode()
    assert "PC-RH-023" in html and "PC-OTRO-1" not in html
    assert client.get(reverse("asset_detail", args=[equipo.pk])).status_code == 200
    assert client.get(reverse("asset_detail", args=[otro.pk])).status_code == 404


def test_el_historial_solo_lo_ve_el_personal_de_soporte(client, usuario, tecnico, equipo):
    Asset.objects.filter(pk=equipo.pk).update(assigned_to=usuario)
    client.force_login(usuario)
    assert "Historial de asignaciones" not in client.get(reverse("asset_detail", args=[equipo.pk])).content.decode()
    client.force_login(tecnico)
    assert "Historial de asignaciones" in client.get(reverse("asset_detail", args=[equipo.pk])).content.decode()


# ---------- Búsqueda y filtros ----------

def test_busqueda_por_ip_y_filtro_por_estado(client, tecnico, equipo):
    Asset.objects.filter(pk=equipo.pk).update(ip_address="192.168.1.43")
    Asset.objects.create(code="SW-001", ip_address="10.0.0.5", status=Asset.Status.REPAIR)
    client.force_login(tecnico)
    html = client.get(reverse("asset_list"), {"q": "192.168"}).content.decode()
    assert "PC-RH-023" in html and "SW-001" not in html
    html = client.get(reverse("asset_list"), {"status": "repair"}).content.decode()
    assert "SW-001" in html and "PC-RH-023" not in html


def test_filtro_sin_asignar(client, tecnico, equipo, usuario):
    libre = Asset.objects.create(code="LIBRE-1")
    Asset.objects.filter(pk=equipo.pk).update(assigned_to=usuario)
    client.force_login(tecnico)
    html = client.get(reverse("asset_list"), {"assigned": "none"}).content.decode()
    assert "LIBRE-1" in html and "PC-RH-023" not in html


# ---------- Datos demo ----------

def test_seed_demo_crea_equipos_y_no_duplica(settings):
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())
    assert Asset.objects.alive().count() == 6
    pc = Asset.objects.get(code="PC-RH-023")
    assert pc.assigned_to.username == "juan.perez" and pc.assignments.count() == 1