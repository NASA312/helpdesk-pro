import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_salud_es_publico_y_responde_ok(client):
    response = client.get(reverse("health"))
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_salud_responde_503_si_la_base_falla(client, monkeypatch):
    class BaseCaida:
        def cursor(self):
            raise RuntimeError("base caída")

    monkeypatch.setattr("apps.core.views.connection", BaseCaida())
    response = client.get(reverse("health"))
    assert response.status_code == 503 and response.json() == {"status": "error"}


def test_salud_no_acepta_post(client):
    assert client.post(reverse("health")).status_code == 405