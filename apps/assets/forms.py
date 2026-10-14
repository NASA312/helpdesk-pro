from django import forms
from django.db.models import Q

from apps.accounts.models import Department, User
from apps.core.forms import TailwindFormMixin

from .models import Asset


class AssetForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Asset
        fields = (
            "code", "asset_type", "brand", "model", "serial_number", "ip_address",
            "operating_system", "status", "assigned_to", "department",
            "purchase_date", "warranty_until", "notes",
        )
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "warranty_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo usuarios activos (más la persona actual, aunque luego se haya desactivado)
        people = Q(is_active=True)
        if self.instance.assigned_to_id:
            people |= Q(pk=self.instance.assigned_to_id)
        self.fields["assigned_to"].queryset = User.objects.filter(people).select_related("department")
        self.fields["assigned_to"].empty_label = "Sin asignar"
        self.fields["assigned_to"].label_from_instance = (
            lambda u: f"{u.display_name} · {u.department or 'Sin departamento'}"
        )

        depts = Q(is_active=True)
        if self.instance.department_id:
            depts |= Q(pk=self.instance.department_id)
        self.fields["department"].queryset = Department.objects.filter(depts)
        self.fields["department"].empty_label = "Sin departamento"

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        qs = Asset.objects.alive().filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un equipo con este código.")
        return code

    def clean_serial_number(self):
        serial = self.cleaned_data["serial_number"].strip()
        if serial:
            qs = Asset.objects.alive().filter(serial_number=serial)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Ya existe un equipo con este número de serie.")
        return serial

    def clean(self):
        cleaned = super().clean()
        purchase, warranty = cleaned.get("purchase_date"), cleaned.get("warranty_until")
        if purchase and warranty and warranty < purchase:
            self.add_error("warranty_until", "La garantía no puede terminar antes de la fecha de compra.")

        person = cleaned.get("assigned_to")
        if person and cleaned.get("status") == Asset.Status.RETIRED:
            self.add_error("assigned_to", "Quita la asignación antes de dar de baja el equipo.")
        if person and not cleaned.get("department"):
            cleaned["department"] = person.department      # hereda el departamento de la persona
        return cleaned