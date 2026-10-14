from datetime import timedelta

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

STATUS_BADGES = {
    "active": "bg-green-100 text-green-800",
    "repair": "bg-yellow-100 text-yellow-800",
    "stored": "bg-slate-200 text-slate-700",
    "retired": "bg-red-100 text-red-800",
}


class AssetQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)


class Asset(models.Model):
    class Type(models.TextChoices):
        COMPUTER = "computer", "Computadora de escritorio"
        LAPTOP = "laptop", "Laptop"
        PRINTER = "printer", "Impresora"
        MONITOR = "monitor", "Monitor"
        NETWORK = "network", "Equipo de red"
        SERVER = "server", "Servidor"
        PHONE = "phone", "Teléfono / móvil"
        OTHER = "other", "Otro"

    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        REPAIR = "repair", "En reparación"
        STORED = "stored", "En almacén"
        RETIRED = "retired", "Dado de baja"

    code = models.CharField(
        "Código", max_length=30,
        validators=[RegexValidator(
            r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
            "Usa solo letras, números, guiones, puntos o guion bajo (sin espacios).",
        )],
        help_text="Ej.: PC-RH-023. Se guarda en mayúsculas.",
    )
    asset_type = models.CharField("Tipo", max_length=20, choices=Type.choices, default=Type.COMPUTER)
    brand = models.CharField("Marca", max_length=60, blank=True)
    model = models.CharField("Modelo", max_length=80, blank=True)
    serial_number = models.CharField("Número de serie", max_length=80, blank=True)
    ip_address = models.GenericIPAddressField("Dirección IP", null=True, blank=True)
    operating_system = models.CharField("Sistema operativo", max_length=80, blank=True)
    status = models.CharField("Estado", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assets", verbose_name="Asignado a",
    )
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assets", verbose_name="Departamento",
    )
    purchase_date = models.DateField("Fecha de compra", null=True, blank=True)
    warranty_until = models.DateField("Garantía hasta", null=True, blank=True)
    notes = models.TextField("Notas", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = AssetQuerySet.as_manager()

    class Meta:
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"
        ordering = ["code"]
        constraints = [
            # Un equipo eliminado libera su código y su número de serie
            models.UniqueConstraint(
                fields=["code"], condition=Q(deleted_at__isnull=True), name="unique_alive_asset_code",
            ),
            models.UniqueConstraint(
                fields=["serial_number"],
                condition=Q(deleted_at__isnull=True) & ~Q(serial_number=""),
                name="unique_alive_asset_serial",
            ),
        ]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["asset_type"])]

    def __str__(self):
        detail = f"{self.brand} {self.model}".strip()
        return f"{self.code} · {detail}" if detail else self.code

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("asset_detail", args=[self.pk])

    @property
    def status_badge(self):
        return STATUS_BADGES[self.status]

    @property
    def warranty_state(self):
        """None sin fecha; 'expired', 'expiring' (30 días o menos) o 'valid'."""
        if not self.warranty_until:
            return None
        today = timezone.localdate()
        if self.warranty_until < today:
            return "expired"
        if self.warranty_until <= today + timedelta(days=30):
            return "expiring"
        return "valid"

    @transaction.atomic
    def soft_delete(self):
        now = timezone.now()
        self.assignments.filter(returned_at__isnull=True).update(returned_at=now)
        self.assigned_to = None
        self.deleted_at = now
        self.save(update_fields=["assigned_to", "deleted_at", "updated_at"])


class AssetAssignment(models.Model):
    """Historial: quién tuvo el equipo y entre qué fechas. returned_at vacío = asignación vigente."""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="asset_assignments"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    returned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Asignación de equipo"
        verbose_name_plural = "Asignaciones de equipos"
        ordering = ["-assigned_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset"], condition=Q(returned_at__isnull=True), name="one_open_assignment_per_asset",
            )
        ]

    def __str__(self):
        return f"{self.asset} → {self.user}"