from django import forms
from django.db.models import Q

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.catalog.models import Category, Priority
from apps.core.forms import TailwindFormMixin
from apps.core.validators import validate_upload

from .models import Ticket


class TicketCreateForm(TailwindFormMixin, forms.ModelForm):
    requester = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label="Solicitante",
        help_text="Solo el personal de soporte puede crear tickets en nombre de otra persona.",
    )
    file = forms.FileField(label="Adjuntar archivo o fotografía (opcional)", required=False)

    field_order = ["requester", "title", "description", "category", "priority", "asset", "file"]

    class Meta:
        model = Ticket
        fields = ("title", "description", "category", "priority", "asset")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
        help_texts = {"asset": "Si el problema es de un equipo en particular, selecciónalo."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["category"].empty_label = "Selecciona una categoría"
        self.fields["priority"].queryset = Priority.objects.filter(is_active=True)
        self.fields["priority"].empty_label = "Selecciona la prioridad"
        self.fields["priority"].label_from_instance = (
            lambda p: f"{p.name} · resolución estimada: {p.resolution_display}"
        )
        default = Priority.objects.filter(is_active=True, level=2).first()
        self.fields["priority"].initial = default.pk if default else None

        assets = Asset.objects.alive().exclude(status=Asset.Status.RETIRED)
        self.fields["asset"].empty_label = "Ninguno / no aplica"
        if user.is_support_staff:
            self.fields["asset"].queryset = assets
            self.fields["requester"].queryset = User.objects.filter(is_active=True).select_related("department")
            self.fields["requester"].empty_label = "Yo mismo"
            self.fields["requester"].label_from_instance = (
                lambda u: f"{u.display_name} · {u.department or 'Sin departamento'}"
            )
        else:
            self.fields["asset"].queryset = assets.filter(assigned_to=user)     # solo SUS equipos
            del self.fields["requester"]

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            validate_upload(file)
        return file


class TicketStaffForm(TailwindFormMixin, forms.ModelForm):
    """Categoría, prioridad y equipo: lo que el soporte puede corregir."""

    class Meta:
        model = Ticket
        fields = ("category", "priority", "asset")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        t = self.instance
        self.fields["category"].queryset = Category.objects.filter(Q(is_active=True) | Q(pk=t.category_id))
        self.fields["priority"].queryset = Priority.objects.filter(Q(is_active=True) | Q(pk=t.priority_id))
        self.fields["asset"].queryset = Asset.objects.alive().filter(
            ~Q(status=Asset.Status.RETIRED) | Q(pk=t.asset_id)
        )
        self.fields["asset"].empty_label = "Ninguno / no aplica"


class AssignForm(TailwindFormMixin, forms.Form):
    assignee = forms.ModelChoiceField(queryset=User.objects.none(), label="Asignar a")

    def __init__(self, *args, ticket, **kwargs):
        super().__init__(*args, **kwargs)
        people = User.objects.filter(is_active=True, role__in=[User.Role.ADMIN, User.Role.TECH])
        if ticket.assigned_to_id:
            people = people.exclude(pk=ticket.assigned_to_id)
        self.fields["assignee"].queryset = people
        self.fields["assignee"].empty_label = "Selecciona una persona"
        self.fields["assignee"].label_from_instance = lambda u: f"{u.display_name} ({u.get_role_display()})"


class StatusForm(TailwindFormMixin, forms.Form):
    status = forms.ChoiceField(label="Nuevo estado")
    note = forms.CharField(
        label="Solución o comentario", required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Obligatorio al resolver (la solución) y al reabrir (el motivo).",
    )

    def __init__(self, *args, ticket, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.ticket = ticket
        labels = dict(Ticket.Status.choices)
        self.fields["status"].choices = [(s, labels[s]) for s in ticket.allowed_transitions(user)]

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        note = (cleaned.get("note") or "").strip()
        cleaned["note"] = note
        S = Ticket.Status
        if status == S.RESOLVED and not note:
            self.add_error("note", "Describe la solución aplicada.")
        reopening = self.ticket.status in (S.RESOLVED, S.CLOSED) and status in (S.IN_PROGRESS, S.NEW)
        if reopening and not note:
            self.add_error("note", "Explica por qué se reabre el ticket.")
        return cleaned


class CommentForm(TailwindFormMixin, forms.Form):
    body = forms.CharField(label="Mensaje", widget=forms.Textarea(attrs={"rows": 3}))
    file = forms.FileField(label="Adjuntar archivo (opcional)", required=False)
    is_internal = forms.BooleanField(
        label="Nota interna (solo la verá el equipo de soporte)", required=False,
    )

    def __init__(self, *args, can_internal=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_internal:
            del self.fields["is_internal"]

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            validate_upload(file)
        return file