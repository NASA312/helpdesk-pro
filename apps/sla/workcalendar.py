from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

MAX_DAYS = 3660          # tope de seguridad (10 años) para no ciclar nunca


@dataclass(frozen=True)
class Calendar:
    """Horario laboral. `always=True` significa atención 24/7."""
    workdays: frozenset          # 0 = lunes ... 6 = domingo
    start: time
    end: time
    tz: tzinfo
    always: bool = False

    def window(self, day):
        """Inicio y fin de la jornada de ese día (en la zona horaria del calendario)."""
        return (
            datetime.combine(day, self.start, tzinfo=self.tz),
            datetime.combine(day, self.end, tzinfo=self.tz),
        )


def add_business_time(cal, start, duration):
    """Fecha en que se cumple `duration` de tiempo laboral contando desde `start`."""
    if duration <= timedelta(0):
        return start
    if cal.always:
        return start + duration

    cur = start.astimezone(cal.tz)
    remaining = duration
    for _ in range(MAX_DAYS):
        day = cur.date()
        if day.weekday() in cal.workdays:
            w_start, w_end = cal.window(day)
            begin = max(cur, w_start)
            if begin < w_end:
                available = w_end - begin
                if remaining <= available:
                    return begin + remaining
                remaining -= available
        cur = datetime.combine(day + timedelta(days=1), time.min, tzinfo=cal.tz)
    raise ValueError("No se encontró tiempo laboral suficiente.")


def business_time_between(cal, start, end):
    """Tiempo laboral transcurrido entre dos momentos (0 si `end` no es posterior a `start`)."""
    if end <= start:
        return timedelta(0)
    if cal.always:
        return end - start

    a, b = start.astimezone(cal.tz), end.astimezone(cal.tz)
    total = timedelta(0)
    day = a.date()
    while day <= b.date():
        if day.weekday() in cal.workdays:
            w_start, w_end = cal.window(day)
            low, high = max(a, w_start), min(b, w_end)
            if low < high:
                total += high - low
        day += timedelta(days=1)
    return total