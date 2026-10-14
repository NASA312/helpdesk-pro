import pytest

from apps.accounts.models import Department, User
from apps.assets.models import Asset
from apps.catalog.models import Category, Priority
from apps.tickets.services import create_ticket

PASSWORD = "Pass12345!"


def make_user(username, role, department=None, **extra):
    return User.objects.create_user(
        username=username, email=f"{username}@test.com", password=PASSWORD,
        first_name=username.capitalize(), last_name="Prueba",
        role=role, department=department, **extra,
    )


@pytest.fixture
def depto(db):
    return Department.objects.create(name="Recursos Humanos")


@pytest.fixture
def administrador(db):
    return make_user("administrador", User.Role.ADMIN)


@pytest.fixture
def tecnico(db):
    return make_user("tecnico", User.Role.TECH)


@pytest.fixture
def usuario(db):
    return make_user("usuario", User.Role.USER)

@pytest.fixture
def equipo(db, depto):
    return Asset.objects.create(
        code="PC-RH-023", asset_type=Asset.Type.COMPUTER, brand="Dell", model="OptiPlex 7090", department=depto,
    )
    
@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    """Los archivos subidos en los tests van a una carpeta temporal."""
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def tecnico2(db):
    return make_user("tecnico2", User.Role.TECH)


@pytest.fixture
def otro_usuario(db):
    return make_user("otrousuario", User.Role.USER)


@pytest.fixture
def categoria(db):
    return Category.objects.get(name="Redes")


@pytest.fixture
def prioridad(db):
    return Priority.objects.get(level=3)       # Alta


@pytest.fixture
def ticket(usuario, categoria, prioridad):
    return create_ticket(
        creator=usuario, requester=usuario, title="Sin Internet",
        description="No hay conexión", category=categoria, priority=prioridad,
    )