from django import forms

from apps.core.forms import TailwindFormMixin

from .models import Category, Priority


class UniqueNameMixin:
    """El nombre no puede repetirse, sin importar mayúsculas."""

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        qs = self._meta.model.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un registro con este nombre.")
        return name


class CategoryForm(TailwindFormMixin, UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description", "is_active")


class PriorityForm(TailwindFormMixin, UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = Priority
        fields = ("name", "level", "color", "response_minutes", "resolution_minutes", "is_active")

    def clean(self):
        cleaned = super().clean()
        # Dentro de clean() la instancia todavía tiene los valores originales
        if self.instance.pk and self.instance.is_active and cleaned.get("is_active") is False:
            others = Priority.objects.filter(is_active=True).exclude(pk=self.instance.pk)
            if not others.exists():
                raise forms.ValidationError("Debe haber al menos una prioridad activa.")
        return cleaned