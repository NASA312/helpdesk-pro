from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.core.mixins import AdminRequiredMixin

from .forms import (
    DepartmentForm, ProfileForm, TailwindPasswordChangeForm, UserCreateForm, UserUpdateForm,
)
from .models import Department, User


# ---------------- Usuarios (solo administrador) ----------------

class UserListView(AdminRequiredMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "people"        # "users"/"user" chocarían con el usuario en sesión
    paginate_by = 15

    def get_queryset(self):
        qs = User.objects.select_related("department")
        params = self.request.GET
        q = params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q)
                | Q(last_name__icontains=q) | Q(email__icontains=q)
            )
        if params.get("role") in User.Role.values:
            qs = qs.filter(role=params["role"])
        if params.get("department", "").isdigit():
            qs = qs.filter(department_id=int(params["department"]))
        if params.get("status") == "active":
            qs = qs.filter(is_active=True)
        elif params.get("status") == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        get = self.request.GET
        params = get.copy()
        params.pop("page", None)
        ctx.update(
            filters={k: get.get(k, "") for k in ("q", "role", "department", "status")},
            roles=User.Role.choices,
            departments=Department.objects.all(),
            extra=("&" + params.urlencode()) if params else "",
        )
        return ctx


class UserCreateView(SuccessMessageMixin, AdminRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("user_list")
    success_message = "Usuario creado correctamente."


class UserUpdateView(SuccessMessageMixin, AdminRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"
    context_object_name = "target_user"   # evita pisar la variable `user` de la sesión
    success_url = reverse_lazy("user_list")
    success_message = "Usuario actualizado."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["acting_user"] = self.request.user
        return kwargs


# ---------------- Departamentos (solo administrador) ----------------

class DepartmentListView(AdminRequiredMixin, ListView):
    template_name = "accounts/department_list.html"
    context_object_name = "departments"

    def get_queryset(self):
        return Department.objects.annotate(user_count=Count("users"))


class DepartmentCreateView(SuccessMessageMixin, AdminRequiredMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = "accounts/department_form.html"
    success_url = reverse_lazy("department_list")
    success_message = "Departamento creado."


class DepartmentUpdateView(SuccessMessageMixin, AdminRequiredMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = "accounts/department_form.html"
    success_url = reverse_lazy("department_list")
    success_message = "Departamento actualizado."


class DepartmentDeleteView(AdminRequiredMixin, DeleteView):
    model = Department
    template_name = "accounts/department_confirm_delete.html"
    success_url = reverse_lazy("department_list")

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                "No se puede eliminar: hay personas en este departamento. Desactívalo en su lugar.",
            )
            return redirect("department_list")
        messages.success(self.request, "Departamento eliminado.")
        return response


# ---------------- Perfil (cualquier usuario) ----------------

class ProfileView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"
    success_url = reverse_lazy("profile")
    success_message = "Perfil actualizado."

    def get_object(self, queryset=None):
        return self.request.user


class PasswordChangeWithMessage(SuccessMessageMixin, PasswordChangeView):
    form_class = TailwindPasswordChangeForm
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("profile")
    success_message = "Contraseña actualizada."