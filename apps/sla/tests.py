from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.urls import reverse

from .models import BusinessSchedule
from .services import apply_deadlines, evaluate_metric, pause, resume
from .workcalendar import Calendar, add_business_time, business_time_between

pytestmark = pytest.mark.django_db

TZ = dt_timezone(timedelta(hours=-6))
CAL = Calendar(workdays=frozenset({0, 1, 2, 3, 4}), start=time(9, 0), end=time(18, 0), tz=TZ)
ALWAYS = Calendar(workdays=frozenset(range(7)), start=time(0, 0), end=time(23, 59), tz=TZ, always=True)


def at(day, hour, minute=0):
    """Octubre de 2026: el 12 es lunes, el 16 viernes, el 17 sábado y el 19 lunes."""
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# ---------- Cálculo de tiempo laboral ----------

def test_suma_dentro_del_horario():
    assert add_business_time(CAL, at(12, 10), timedelta(minutes=15)) == at(12, 10, 15)


def test_suma_que_cruza_al_dia_siguiente():
    assert add_business_time(CAL, at(12, 17), timedelta(hours=2)) == at(13, 10)


def test_suma_que_salta_el_fin_de_semana():
    assert add_business_time(CAL, at(16, 17, 50), timedelta(minutes=30)) == at(19, 9, 20)


def test_ticket_creado_en_fin_de_semana_empieza_el_lunes():
    assert add_business_time(CAL, at(17, 12), timedelta(hours=1)) == at(19, 10)


def test_ticket_creado_antes_del_horario_empieza_a_las_nueve():
    assert add_business_time(CAL, at(12, 8), timedelta(minutes=30)) == at(12, 9, 30)


def test_plazo_que_termina_justo_al_cierre():
    assert add_business_time(CAL, at(12, 17, 30), timedelta(minutes=30)) == at(12, 18)


def test_atencion_24x7_corre_siempre():
    assert add_business_time(ALWAYS, at(17, 12), timedelta(minutes=90)) == at(17, 13, 30)
    assert business_time_between(ALWAYS, at(17, 12), at(18, 12)) == timedelta(hours=24)


def test_duracion_cero_devuelve_el_mismo_momento():
    assert add_business_time(CAL, at(12, 10), timedelta(0)) == at(12, 10)


def test_tiempo_laboral_entre_dos_momentos():
    assert business_time_between(CAL, at(12, 17), at(13, 10)) == timedelta(hours=2)
    assert business_time_between(CAL, at(16, 17), at(19, 10)) == timedelta(hours=2)    # salta el fin de semana
    assert business_time_between(CAL, at(17, 9), at(18, 20)) == timedelta(0)           # sábado y domingo
    assert business_time_between(CAL, at(12, 12), at(12, 11)) == timedelta(0)


# ---------- Estado de un plazo ----------

def metric(now=at(12, 11), done_at=None, paused_at=None):
    created, base = at(12, 10), timedelta(hours=4)
    due = add_business_time(CAL, created, base)                      # lunes 14:00
    return evaluate_metric(
        CAL, kind="Resolución", created=created, due=due, base=base,
        done_at=done_at, paused_at=paused_at, now=now,
    )


def test_en_tiempo():
    m = metric(now=at(12, 11))
    assert m["state"] == "ok" and m["pct"] == 25 and m["short"] == "3 h"


def test_por_vencer_al_pasar_el_75_por_ciento():
    assert metric(now=at(12, 13, 30))["state"] == "warning"


def test_incumplido_en_curso():
    m = metric(now=at(12, 15))
    assert m["state"] == "breached" and m["pct"] == 100 and "1 h" in m["detail"]


def test_cumplido_a_tiempo_y_fuera_de_tiempo():
    assert metric(now=at(12, 20), done_at=at(12, 13))["state"] == "met"
    late = metric(now=at(12, 20), done_at=at(12, 15))
    assert late["state"] == "missed" and late["short"] == "+1 h"


def test_pausado_congela_el_reloj():
    m = metric(now=at(13, 10), paused_at=at(12, 12))
    assert m["state"] == "paused" and m["pct"] == 50


def test_plazo_cancelado_o_sin_plazo_no_aplica():
    assert evaluate_metric(
        CAL, kind="X", created=at(12, 10), due=None, base=timedelta(hours=1),
        done_at=None, paused_at=None, now=at(12, 11),
    )["state"] == "na"


# ---------- Plazos, pausa y reanudación ----------

def fake_ticket():
    t = SimpleNamespace(
        created_at=at(12, 10), priority=SimpleNamespace(response_minutes=30, resolution_minutes=240),
        sla_paused_at=None, sla_paused_seconds=0, response_due_at=None, resolution_due_at=None,
    )
    apply_deadlines(t, CAL)
    return t


def test_plazos_iniciales():
    t = fake_ticket()
    assert t.response_due_at == at(12, 10, 30) and t.resolution_due_at == at(12, 14)


def test_pausa_y_reanudacion_extienden_el_plazo_solo_con_tiempo_laboral():
    t = fake_ticket()
    pause(t, at(12, 12))
    pause(t, at(12, 13))                           # una segunda pausa no mueve el inicio
    assert t.sla_paused_at == at(12, 12)
    resume(t, at(13, 10), CAL)                     # lunes 12:00 -> martes 10:00 = 6 h + 1 h laborales
    assert t.sla_paused_at is None and t.sla_paused_seconds == 7 * 3600
    assert t.resolution_due_at == at(13, 12)       # quedaban 2 h: martes 10:00 + 2 h


def test_reanudar_sin_pausa_no_hace_nada():
    t = fake_ticket()
    before = t.resolution_due_at
    resume(t, at(12, 12), CAL)
    assert t.resolution_due_at == before and t.sla_paused_seconds == 0


def test_cambiar_la_prioridad_recalcula_los_plazos():
    t = fake_ticket()
    t.priority = SimpleNamespace(response_minutes=15, resolution_minutes=120)
    apply_deadlines(t, CAL)
    assert t.response_due_at == at(12, 10, 15) and t.resolution_due_at == at(12, 12)


# ---------- Horario laboral (pantalla de configuración) ----------

SCHEDULE = {"workdays": ["0", "1", "2"], "start_time": "08:00", "end_time": "17:00"}


def test_horario_por_defecto():
    s = BusinessSchedule.get()
    assert s.workday_numbers == {0, 1, 2, 3, 4} and not s.is_24x7
    assert (s.start_time, s.end_time) == (time(9, 0), time(18, 0))


def test_solo_el_administrador_configura_el_horario(client, administrador, tecnico, usuario):
    for person in (tecnico, usuario):
        client.force_login(person)
        assert client.get(reverse("sla_schedule")).status_code == 403
    client.force_login(administrador)
    assert client.get(reverse("sla_schedule")).status_code == 200


def test_guardar_horario_valido(client, administrador):
    client.force_login(administrador)
    assert client.post(reverse("sla_schedule"), SCHEDULE).status_code == 302
    s = BusinessSchedule.get()
    assert s.workday_numbers == {0, 1, 2} and s.start_time == time(8, 0) and s.end_time == time(17, 0)


@pytest.mark.parametrize("override", [
    {"start_time": "18:00", "end_time": "09:00"},
    {"workdays": []},
])
def test_horario_invalido_se_rechaza(client, administrador, override):
    client.force_login(administrador)
    assert client.post(reverse("sla_schedule"), {**SCHEDULE, **override}).status_code == 200
    assert BusinessSchedule.get().workday_numbers == {0, 1, 2, 3, 4}


def test_modo_24x7_no_exige_dias_y_recalcula_los_tickets_abiertos(client, administrador, ticket):
    client.force_login(administrador)
    assert client.post(reverse("sla_schedule"), {"is_24x7": "on", "start_time": "09:00", "end_time": "18:00"}).status_code == 302
    ticket.refresh_from_db()
    assert ticket.resolution_due_at == ticket.created_at + timedelta(minutes=240)       # Alta: 4 horas