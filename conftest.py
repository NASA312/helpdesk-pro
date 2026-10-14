import pytest

from apps.accounts.models import Department, User

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