from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse

from conftest import PASSWORD, make_user

from .models import Department, User

pytestmark = pytest.mark.django_db


def update_data(user, **override):
    data = {
        "username": user.username, "first_name": user.first_name, "last_name": user.last_name,
        "email": user.email, "role": user.role, "department": "", "job_title": "", "phone": "",
        "is_active": "on",
    }
    data.update(override)
    return data


# ---------- Modelo ----------

def test_superusuario_nace_como_administrador():
    su = User.objects.create_superuser("root", "root@test.com", PASSWORD)
    assert su.role == User.Role.ADMIN and su.is_helpdesk_admin


def test_el_correo_se_guarda_en_minusculas():
    u = User.objects.create_user("ana", "Ana@Test.COM", PASSWORD)
    assert u.email == "ana@test.com"


def test_propiedades_de_rol(administrador, tecnico, usuario):
    assert administrador.is_helpdesk_admin and administrador.is_support_staff
    assert tecnico.is_technician and tecnico.is_support_staff and not tecnico.is_helpdesk_admin
    assert not usuario.is_support_staff


# ---------- Acceso ----------

@pytest.mark.parametrize("name", ["dashboard", "user_list", "user_create", "department_list", "profile"])
def test_anonimo_es_redirigido_al_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302 and response.url.startswith(reverse("login"))


@pytest.mark.parametrize("name", ["user_list", "user_create", "department_list", "department_create"])
def test_solo_el_administrador_gestiona(client, administrador, tecnico, usuario, name):
    for person in (tecnico, usuario):
        client.force_login(person)
        assert client.get(reverse(name)).status_code == 403
    client.force_login(administrador)
    assert client.get(reverse(name)).status_code == 200


def test_el_panel_responde_para_todos_los_roles(client, administrador, tecnico, usuario):
    for person in (administrador, tecnico, usuario):
        client.force_login(person)
        assert client.get(reverse("dashboard")).status_code == 200


# ---------- Login ----------

def test_login_con_usuario_o_con_correo(usuario):
    for identifier in (usuario.username, usuario.email.upper()):
        c = Client()
        response = c.post(reverse("login"), {"username": identifier, "password": PASSWORD})
        assert response.status_code == 302 and "_auth_user_id" in c.session


def test_login_con_contrasena_incorrecta(client, usuario):
    response = client.post(reverse("login"), {"username": usuario.username, "password": "mala"})
    assert response.status_code == 200 and "_auth_user_id" not in client.session


def test_usuario_inactivo_no_puede_entrar(client, usuario):
    usuario.is_active = False
    usuario.save()
    response = client.post(reverse("login"), {"username": usuario.username, "password": PASSWORD})
    assert response.status_code == 200 and "_auth_user_id" not in client.session


# ---------- Gestión de usuarios ----------

def test_admin_crea_usuario(client, administrador, depto):
    client.force_login(administrador)
    data = {
        "username": "nuevo", "first_name": "Nora", "last_name": "Gil", "email": "Nora@Test.com",
        "role": "tech", "department": depto.pk, "job_title": "Soporte", "phone": "",
        "password1": "Clave-Segura-2026", "password2": "Clave-Segura-2026",
    }
    assert client.post(reverse("user_create"), data).status_code == 302
    u = User.objects.get(username="nuevo")
    assert u.role == User.Role.TECH and u.email == "nora@test.com" and u.department == depto
    assert u.check_password("Clave-Segura-2026")


def test_correo_duplicado_se_rechaza_sin_importar_mayusculas(client, administrador, usuario):
    client.force_login(administrador)
    data = {
        "username": "otro", "first_name": "O", "last_name": "T", "email": usuario.email.upper(),
        "role": "user", "department": "", "job_title": "", "phone": "",
        "password1": "Clave-Segura-2026", "password2": "Clave-Segura-2026",
    }
    assert client.post(reverse("user_create"), data).status_code == 200
    assert not User.objects.filter(username="otro").exists()


def test_admin_cambia_el_rol_de_otro_usuario(client, administrador, usuario):
    client.force_login(administrador)
    response = client.post(reverse("user_update", args=[usuario.pk]), update_data(usuario, role="tech"))
    assert response.status_code == 302
    usuario.refresh_from_db()
    assert usuario.role == User.Role.TECH


def test_el_unico_administrador_no_puede_degradarse(client, administrador):
    client.force_login(administrador)
    response = client.post(
        reverse("user_update", args=[administrador.pk]), update_data(administrador, role="tech")
    )
    assert response.status_code == 200
    administrador.refresh_from_db()
    assert administrador.role == User.Role.ADMIN


def test_un_administrador_no_puede_desactivarse_a_si_mismo(client, administrador):
    otro = make_user("admin2", User.Role.ADMIN)
    client.force_login(administrador)
    data = update_data(administrador)
    data.pop("is_active")
    assert client.post(reverse("user_update", args=[administrador.pk]), data).status_code == 200
    administrador.refresh_from_db()
    assert administrador.is_active

    data = update_data(otro)                       # pero sí puede desactivar al otro
    data.pop("is_active")
    assert client.post(reverse("user_update", args=[otro.pk]), data).status_code == 302
    otro.refresh_from_db()
    assert not otro.is_active


def test_listado_filtra_por_rol_y_por_texto(client, administrador, tecnico, usuario):
    client.force_login(administrador)
    html = client.get(reverse("user_list"), {"role": "tech"}).content.decode()
    assert tecnico.email in html and usuario.email not in html
    html = client.get(reverse("user_list"), {"q": "usuario"}).content.decode()
    assert usuario.email in html and tecnico.email not in html


# ---------- Departamentos ----------

def test_departamento_con_personas_no_se_elimina(client, administrador, depto, usuario):
    usuario.department = depto
    usuario.save()
    client.force_login(administrador)
    assert client.post(reverse("department_delete", args=[depto.pk])).status_code == 302
    assert Department.objects.filter(pk=depto.pk).exists()


def test_departamento_vacio_se_elimina(client, administrador, depto):
    client.force_login(administrador)
    assert client.post(reverse("department_delete", args=[depto.pk])).status_code == 302
    assert not Department.objects.filter(pk=depto.pk).exists()


def test_admin_crea_departamento(client, administrador):
    client.force_login(administrador)
    response = client.post(reverse("department_create"), {"name": "Ventas", "description": "", "is_active": "on"})
    assert response.status_code == 302 and Department.objects.filter(name="Ventas").exists()


# ---------- Perfil ----------

def test_usuario_edita_su_perfil_pero_no_su_rol(client, usuario):
    client.force_login(usuario)
    data = {
        "first_name": "Juan", "last_name": "Pérez", "email": usuario.email,
        "phone": "311 000 0000", "job_title": "Analista", "role": "admin",     # "role" debe ignorarse
    }
    assert client.post(reverse("profile"), data).status_code == 302
    usuario.refresh_from_db()
    assert usuario.phone == "311 000 0000" and usuario.role == User.Role.USER


def test_cambiar_contrasena(client, usuario):
    client.force_login(usuario)
    data = {"old_password": PASSWORD, "new_password1": "Otra-Clave-Segura-77", "new_password2": "Otra-Clave-Segura-77"}
    assert client.post(reverse("password_change"), data).status_code == 302
    usuario.refresh_from_db()
    assert usuario.check_password("Otra-Clave-Segura-77")


# ---------- Datos demo ----------

def test_seed_demo_es_idempotente(settings):
    settings.DEBUG = True
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())
    assert User.objects.filter(username="mario.mata", role="tech").count() == 1
    assert Department.objects.count() == 5


def test_seed_demo_se_niega_sin_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo", stdout=StringIO())