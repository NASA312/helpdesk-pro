import uuid
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

STATUS_BADGES = {
    "new": "bg-blue-100 text-blue-800",
    "assigned": "bg-indigo-100 text-indigo-800",
    "in_progress": "bg-amber-100 text-amber-800",
    "waiting_user": "bg-purple-100 text-purple-800",
    "resolved": "bg-green-100 text-green-800",
    "closed": "bg-slate-200 text-slate-700",
}

# Cambios de estado que puede hacer el personal de soporte que atiende el ticket
STAFF_TRANSITIONS = {
    "assigned": ["in_progress", "waiting_user", "resolved"],
    "in_progress": ["waiting_user", "resolved"],
    "waiting_user": ["in_progress", "resolved"],
    "resolved": ["in_progress", "closed"],
}
OPEN_FOR_REQUESTER = ["new", "assigned", "in_progress", "waiting_user", "resolved"]


class TicketCounter(models.Model):
    """Una sola fila (pk=1) que entrega los números de ticket sin repetirlos."""
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Contador de tickets"
        verbose_name_plural = "Contador de tickets"

    @classmethod
    def next_number(cls):
        # El bloqueo de fila dura hasta el final de la transacción: dos tickets simultáneos se ponen en fila
        with transaction.atomic():
            counter, _ = cls.objects.select_for_update().get_or_create(pk=1)
            counter.last_number += 1
            counter.save(update_fields=["last_number"])
            return counter.last_number


class TicketQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def active(self):
        """Tickets sin resolver."""
        return self.exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
    
    def sla_breached(self):
        """Tickets sin resolver cuyo plazo ya venció y cuyo reloj no está en pausa."""
        now = timezone.now()
        return self.active().filter(
            Q(first_response_at__isnull=True, response_due_at__lt=now)
            | (
                Q(resolution_due_at__lt=now)
                & (Q(sla_paused_at__isnull=True) | Q(sla_paused_at__gt=F("resolution_due_at")))
            )
        )

    def for_user(self, user):
        """Tickets que `user` puede ver."""
        qs = self.alive()
        if not user.is_authenticated:
            return qs.none()
        if user.is_helpdesk_admin:
            return qs
        if user.is_technician:
            return qs.filter(
                Q(assigned_to=user) | Q(requester=user)
                | Q(assigned_to__isnull=True, status=Ticket.Status.NEW)       # cola sin asignar
            )
        return qs.filter(requester=user)


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Nuevo"
        ASSIGNED = "assigned", "Asignado"
        IN_PROGRESS = "in_progress", "En proceso"
        WAITING_USER = "waiting_user", "Esperando usuario"
        RESOLVED = "resolved", "Resuelto"
        CLOSED = "closed", "Cerrado"

    number = models.PositiveIntegerField("Número", unique=True, editable=False)
    title = models.CharField("Título", max_length=200)
    description = models.TextField("Descripción")
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="tickets", verbose_name="Categoría",
    )
    priority = models.ForeignKey(
        "catalog.Priority", on_delete=models.PROTECT, related_name="tickets", verbose_name="Prioridad",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets",
        verbose_name="Solicitante",
    )
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets", verbose_name="Departamento",
    )
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="tickets", verbose_name="Equipo",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_tickets", verbose_name="Técnico asignado",
    )
    status = models.CharField("Estado", max_length=20, choices=Status.choices, default=Status.NEW)
    solution = models.TextField("Solución", blank=True)

    # Momentos que usará el SLA (Fase 4)
    assigned_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Plazos del SLA (los calcula apps.sla.services)
    response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    sla_paused_at = models.DateTimeField(null=True, blank=True)
    sla_paused_seconds = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = TicketQuerySet.as_manager()

    class Meta:
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["resolution_due_at"]),
        ]

    def __str__(self):
        return f"{self.code} · {self.title}"

    @property
    def code(self):
        return f"TK-{self.number:06d}"

    def get_absolute_url(self):
        return reverse("ticket_detail", args=[self.pk])

    @property
    def status_badge(self):
        return STATUS_BADGES[self.status]

    @property
    def is_open(self):
        return self.status not in (self.Status.RESOLVED, self.Status.CLOSED)

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    # ---------------- Permisos sobre ESTE ticket ----------------

    def user_is_requester(self, user):
        return self.requester_id == user.pk

    def user_can_work(self, user):
        """Atenderlo: el administrador, o el técnico al que está asignado."""
        if not user.is_authenticated:
            return False
        if user.is_helpdesk_admin:
            return True
        return user.is_technician and self.assigned_to_id == user.pk

    def user_can_take(self, user):
        return user.is_support_staff and self.assigned_to_id is None and self.status == self.Status.NEW

    def user_can_assign(self, user):
        if self.status in (self.Status.RESOLVED, self.Status.CLOSED):
            return False
        return self.user_can_work(user) or self.user_can_take(user)

    def user_can_comment(self, user):
        if self.status == self.Status.CLOSED:
            return False
        return self.user_is_requester(user) or self.user_can_work(user)

    def user_can_see_internal(self, user):
        return self.user_can_work(user)

    def allowed_transitions(self, user):
        """Estados a los que `user` puede mover este ticket ahora mismo."""
        S = self.Status
        allowed = []
        if self.user_can_work(user):
            allowed += STAFF_TRANSITIONS.get(self.status, [])
            if user.is_helpdesk_admin and self.status == S.CLOSED:
                # Reabrir: si nunca tuvo técnico, vuelve a la cola
                allowed.append(S.IN_PROGRESS if self.assigned_to_id else S.NEW)
        if self.user_is_requester(user):
            if self.status in OPEN_FOR_REQUESTER:
                allowed.append(S.CLOSED)
            if self.status == S.RESOLVED:
                allowed.append(S.IN_PROGRESS)
        return list(dict.fromkeys(str(s) for s in allowed))      # sin repetidos, en orden


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="ticket_comments"
    )
    body = models.TextField("Mensaje")
    is_internal = models.BooleanField("Nota interna", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Comentario"
        verbose_name_plural = "Comentarios"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.author}: {self.body[:40]}"


def attachment_path(instance, filename):
    return f"tickets/{instance.ticket_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(
        TicketComment, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="ticket_attachments"
    )
    file = models.FileField(upload_to=attachment_path)
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Adjunto"
        verbose_name_plural = "Adjuntos"
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.filename


class TicketEvent(models.Model):
    """Historial del ticket. Lo escribe el servidor, nunca el navegador."""

    class Kind(models.TextChoices):
        CREATED = "created", "Creación"
        ASSIGNED = "assigned", "Asignación"
        STATUS = "status", "Estado"
        UPDATED = "updated", "Edición"
        COMMENT = "comment", "Comentario"
        NOTE = "note", "Nota interna"
        FILE = "file", "Archivo"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.CharField(max_length=255)
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Evento"
        verbose_name_plural = "Historial"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["ticket", "created_at"])]

    def __str__(self):
        return f"{self.ticket.code}: {self.message}"