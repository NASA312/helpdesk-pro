from datetime import time

from django.db import models


class BusinessSchedule(models.Model):
    """Una sola fila (pk=1): el horario laboral que usa el SLA."""
    DAYS = [(0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"), (4, "Viernes"), (5, "Sábado"), (6, "Domingo")]

    is_24x7 = models.BooleanField(
        "Atención 24/7", default=False,
        help_text="Si se activa, el reloj corre las 24 horas, todos los días.",
    )
    workdays = models.CharField("Días laborables", max_length=13, blank=True, default="0,1,2,3,4")
    start_time = models.TimeField("Hora de inicio", default=time(9, 0))
    end_time = models.TimeField("Hora de fin", default=time(18, 0))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Horario laboral"
        verbose_name_plural = "Horario laboral"

    def __str__(self):
        return "Atención 24/7" if self.is_24x7 else f"{self.start_time:%H:%M} - {self.end_time:%H:%M}"

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def workday_numbers(self):
        return {int(n) for n in self.workdays.split(",") if n.strip().isdigit()}