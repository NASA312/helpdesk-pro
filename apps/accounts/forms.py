from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.db.models import Q

from apps.core.forms import TailwindFormMixin

from .models import Department, User


class LoginForm(TailwindFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario o correo"
        self.fields["username"].widget.attrs.update({"autofocus": True, "autocomplete": "username"})


class TailwindPasswordChangeForm(TailwindFormMixin, PasswordChangeForm):
    pass


class EmailCleanMixin:
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Ya existe un usuario con este correo.")
        return email


class UserFormMixin(TailwindFormMixin, EmailCleanMixin):
    """Base de los formularios de alta y edición que usa el administrador."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo departamentos activos (más el actual, si la persona ya estaba en uno inactivo)
        condition = Q(is_active=True)
        if self.instance.pk and self.instance.department_id:
            condition |= Q(pk=self.instance.department_id)
        self.fields["department"].queryset = Department.objects.filter(condition)
        self.fields["department"].empty_label = "Sin departamento"
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True


class UserCreateForm(UserFormMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role", "department", "job_title", "phone")


class UserUpdateForm(UserFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "username", "first_name", "last_name", "email", "role",
            "department", "job_title", "phone", "is_active",
        )
        labels = {"is_active": "Cuenta activa"}
        help_texts = {"is_active": "Si se desmarca, la persona ya no podrá iniciar sesión."}

    def __init__(self, *args, **kwargs):
        self.acting_user = kwargs.pop("acting_user", None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        # OJO: dentro de clean() la instancia todavía tiene los valores originales
        if not self.instance.pk or self.instance.role != User.Role.ADMIN:
            return cleaned
        losing_admin = cleaned.get("role") != User.Role.ADMIN or cleaned.get("is_active") is False
        if losing_admin:
            others = User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(pk=self.instance.pk)
            if not others.exists():
                raise forms.ValidationError("Debe existir al menos un administrador activo.")
            if self.acting_user and self.acting_user.pk == self.instance.pk:
                raise forms.ValidationError("No puedes quitarte tu propio acceso de administrador.")
        return cleaned


class ProfileForm(TailwindFormMixin, EmailCleanMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "job_title", "phone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email"):
            self.fields[name].required = True


class DepartmentForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ("name", "description", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}