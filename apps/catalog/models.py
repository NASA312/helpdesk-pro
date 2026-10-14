from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.utils import format_minutes


class Category(models.Model):
    name = models.CharField("Nombre", max_length=100, unique=True)
    description = models.CharField("Descripción", max_length=255, blank=True)
    is_active = models.BooleanField("Activa", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Priority(models.Model):
    class Color(models.TextChoices):
        RED = "red", "Rojo"
        ORANGE = "orange", "Naranja"
        YELLOW = "yellow", "Amarillo"
        GREEN = "green", "Verde"
        BLUE = "blue", "Azul"
        SLATE = "slate", "Gris"

    # Clases completas (Tailwind las detecta al compilar para producción)
    BADGES = {
        "red": "bg-red-100 text-red-800",
        "orange": "bg-orange-100 text-orange-800",
        "yellow": "bg-yellow-100 text-yellow-800",
        "green": "bg-green-100 text-green-800",
        "blue": "bg-blue-100 text-blue-800",
        "slate": "bg-slate-200 text-slate-700",
    }

    name = models.CharField("Nombre", max_length=50, unique=True)
    level = models.PositiveSmallIntegerField(
        "Nivel", unique=True, validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="De 1 a 10. Mayor número = más urgente. No puede repetirse.",
    )
    color = models.CharField("Color", max_length=10, choices=Color.choices, default=Color.SLATE)
    response_minutes = models.PositiveIntegerField(
        "Tiempo de respuesta (min)", validators=[MinValueValidator(1)],
        help_text="En minutos. Ej.: 30 = 30 minutos, 120 = 2 horas.",
    )
    resolution_minutes = models.PositiveIntegerField(
        "Tiempo de resolución (min)", validators=[MinValueValidator(1)],
        help_text="En minutos. Ej.: 480 = 8 horas, 1440 = 24 horas.",
    )
    is_active = models.BooleanField("Activa", default=True)

    class Meta:
        verbose_name = "Prioridad"
        verbose_name_plural = "Prioridades"
        ordering = ["-level"]

    def __str__(self):
        return self.name

    def clean(self):
        if (
            self.response_minutes and self.resolution_minutes
            and self.resolution_minutes < self.response_minutes
        ):
            raise ValidationError(
                {"resolution_minutes": "La resolución no puede ser menor que el tiempo de respuesta."}
            )

    @property
    def badge_classes(self):
        return self.BADGES.get(self.color, self.BADGES["slate"])

    @property
    def response_display(self):
        return format_minutes(self.response_minutes)

    @property
    def resolution_display(self):
        return format_minutes(self.resolution_minutes)