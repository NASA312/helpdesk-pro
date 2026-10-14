import pytest
from django.db.models import ProtectedError
from django.urls import reverse

from apps.core.utils import format_minutes

from .models import Category, Priority

pytestmark = pytest.mark.django_db


def priority_data(p, **override):
    data = {
        "name": p.name, "level": p.level, "color": p.color,
        "response_minutes": p.response_minutes, "resolution_minutes": p.resolution_minutes, "is_active": "on",
    }
    data.update(override)
    return data


# ---------- Datos por defecto (migración) ----------

def test_prioridades_por_defecto():
    rows = list(Priority.objects.order_by("-level").values_list("name", "level", "response_minutes", "resolution_minutes"))
    assert rows == [("Crítica", 4, 15, 120), ("Alta", 3, 30, 240), ("Media", 2, 120, 480), ("Baja", 1, 480, 1440)]


def test_categorias_por_defecto():
    assert Category.objects.filter(name__in=["Redes", "Hardware", "Software", "Correo"]).count() == 4


@pytest.mark.parametrize("minutes,text", [(15, "15 min"), (60, "1 h"), (90, "1 h 30 min"), (120, "2 h"), (1440, "24 h")])
def test_format_minutes(minutes, text):
    assert format_minutes(minutes) == text


# ---------- Permisos ----------

@pytest.mark.parametrize("name", ["category_list", "category_create", "priority_list", "priority_create"])
def test_solo_el_administrador_gestiona_catalogos(client, administrador, tecnico, usuario, name):
    for person in (tecnico, usuario):
        client.force_login(person)
        assert client.get(reverse(name)).status_code == 403
    client.force_login(administrador)
    assert client.get(reverse(name)).status_code == 200


def test_anonimo_es_redirigido_al_login(client):
    assert client.get(reverse("priority_list")).status_code == 302


# ---------- Categorías ----------

def test_crear_categoria(client, administrador):
    client.force_login(administrador)
    response = client.post(reverse("category_create"), {"name": "Telefonía", "description": "", "is_active": "on"})
    assert response.status_code == 302 and Category.objects.filter(name="Telefonía").exists()


def test_nombre_de_categoria_repetido_se_rechaza_sin_importar_mayusculas(client, administrador):
    client.force_login(administrador)
    response = client.post(reverse("category_create"), {"name": "redes", "description": "", "is_active": "on"})
    assert response.status_code == 200
    assert Category.objects.filter(name__iexact="redes").count() == 1


def test_eliminar_categoria(client, administrador):
    c = Category.objects.create(name="Temporal")
    client.force_login(administrador)
    assert client.post(reverse("category_delete", args=[c.pk])).status_code == 302
    assert not Category.objects.filter(pk=c.pk).exists()


# ---------- Prioridades ----------

def test_lista_de_prioridades_muestra_tiempos_legibles(client, administrador):
    client.force_login(administrador)
    html = client.get(reverse("priority_list")).content.decode()
    assert "Crítica" in html and "15 min" in html and "24 h" in html


def test_crear_prioridad(client, administrador):
    client.force_login(administrador)
    data = {"name": "Planificada", "level": 5, "color": "blue", "response_minutes": 60,
            "resolution_minutes": 2880, "is_active": "on"}
    assert client.post(reverse("priority_create"), data).status_code == 302
    assert Priority.objects.get(name="Planificada").resolution_display == "48 h"


def test_resolucion_menor_que_respuesta_se_rechaza(client, administrador):
    alta = Priority.objects.get(level=3)
    client.force_login(administrador)
    response = client.post(
        reverse("priority_update", args=[alta.pk]), priority_data(alta, response_minutes=60, resolution_minutes=30)
    )
    assert response.status_code == 200
    alta.refresh_from_db()
    assert alta.response_minutes == 30


def test_nivel_repetido_se_rechaza(client, administrador):
    client.force_login(administrador)
    data = {"name": "Otra", "level": 4, "color": "red", "response_minutes": 5,
            "resolution_minutes": 10, "is_active": "on"}
    assert client.post(reverse("priority_create"), data).status_code == 200
    assert not Priority.objects.filter(name="Otra").exists()


def test_editar_tiempos_de_sla(client, administrador):
    media = Priority.objects.get(level=2)
    client.force_login(administrador)
    response = client.post(
        reverse("priority_update", args=[media.pk]), priority_data(media, response_minutes=90, resolution_minutes=600)
    )
    assert response.status_code == 302
    media.refresh_from_db()
    assert media.response_display == "1 h 30 min" and media.resolution_display == "10 h"


def test_no_se_puede_desactivar_la_ultima_prioridad_activa(client, administrador):
    baja = Priority.objects.get(level=1)
    Priority.objects.exclude(pk=baja.pk).update(is_active=False)
    data = priority_data(baja)
    data.pop("is_active")
    client.force_login(administrador)
    assert client.post(reverse("priority_update", args=[baja.pk]), data).status_code == 200
    baja.refresh_from_db()
    assert baja.is_active


def test_si_hay_otra_activa_si_se_puede_desactivar(client, administrador):
    baja = Priority.objects.get(level=1)
    data = priority_data(baja)
    data.pop("is_active")
    client.force_login(administrador)
    assert client.post(reverse("priority_update", args=[baja.pk]), data).status_code == 302
    baja.refresh_from_db()
    assert not baja.is_active