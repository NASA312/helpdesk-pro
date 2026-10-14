from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.accounts.models import Department
from apps.core.mixins import AdminRequiredMixin, FormPageMixin, SupportStaffRequiredMixin

from .forms import AssetForm
from .models import Asset
from .services import sync_assignment


class AssetListView(SupportStaffRequiredMixin, ListView):
    template_name = "assets/asset_list.html"
    context_object_name = "assets"
    paginate_by = 20

    def get_queryset(self):
        qs = Asset.objects.alive().select_related("assigned_to", "department")
        p = self.request.GET
        q = p.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q) | Q(brand__icontains=q) | Q(model__icontains=q)
                | Q(serial_number__icontains=q) | Q(ip_address__icontains=q)
                | Q(assigned_to__first_name__icontains=q) | Q(assigned_to__last_name__icontains=q)
                | Q(assigned_to__username__icontains=q)
            )
        if p.get("type") in Asset.Type.values:
            qs = qs.filter(asset_type=p["type"])
        if p.get("status") in Asset.Status.values:
            qs = qs.filter(status=p["status"])
        if p.get("department", "").isdigit():
            qs = qs.filter(department_id=int(p["department"]))
        if p.get("assigned") == "none":
            qs = qs.filter(assigned_to__isnull=True)
        elif p.get("assigned") == "yes":
            qs = qs.filter(assigned_to__isnull=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        get = self.request.GET
        params = get.copy()
        params.pop("page", None)
        ctx.update(
            filters={k: get.get(k, "") for k in ("q", "type", "status", "department", "assigned")},
            types=Asset.Type.choices,
            statuses=Asset.Status.choices,
            departments=Department.objects.all(),
            extra=("&" + params.urlencode()) if params else "",
        )
        return ctx


class MyAssetsView(LoginRequiredMixin, ListView):
    """Los equipos asignados a la persona en sesión (cualquier rol)."""
    template_name = "assets/my_assets.html"
    context_object_name = "assets"

    def get_queryset(self):
        return Asset.objects.alive().filter(assigned_to=self.request.user).select_related("department")


class AssetDetailView(LoginRequiredMixin, DetailView):
    template_name = "assets/asset_detail.html"
    context_object_name = "asset"

    def get_queryset(self):
        qs = Asset.objects.alive().select_related("assigned_to", "department")
        user = self.request.user
        # Quien no es de soporte solo ve SUS equipos; los demás dan 404
        return qs if user.is_support_staff else qs.filter(assigned_to=user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.user.is_support_staff:
            ctx["history"] = self.object.assignments.select_related("user", "assigned_by")
        return ctx


class AssetCreateView(SuccessMessageMixin, FormPageMixin, SupportStaffRequiredMixin, CreateView):
    model = Asset
    form_class = AssetForm
    template_name = "core/form_page.html"
    success_message = "Equipo registrado."
    page_title = "Nuevo equipo"
    cancel_url_name = "asset_list"

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        sync_assignment(self.object, None, self.request.user)
        return response


class AssetUpdateView(SuccessMessageMixin, FormPageMixin, SupportStaffRequiredMixin, UpdateView):
    form_class = AssetForm
    template_name = "core/form_page.html"
    success_message = "Equipo actualizado."

    def get_queryset(self):
        return Asset.objects.alive()

    def get_page_title(self):
        return f"Editar {self.object.code}"

    def get_cancel_url(self):
        return self.object.get_absolute_url()

    @transaction.atomic
    def form_valid(self, form):
        previous = form.initial.get("assigned_to")      # quién lo tenía antes de editar
        response = super().form_valid(form)
        sync_assignment(self.object, previous, self.request.user)
        return response


class AssetDeleteView(FormPageMixin, AdminRequiredMixin, DeleteView):
    template_name = "core/confirm_delete.html"
    page_title = "Eliminar equipo"
    warning = "Dejará de mostrarse en el inventario, pero se conserva su historial."

    def get_queryset(self):
        return Asset.objects.alive()

    def get_cancel_url(self):
        return self.object.get_absolute_url()

    def form_valid(self, form):
        self.object.soft_delete()
        messages.success(self.request, "Equipo eliminado.")
        return HttpResponseRedirect(reverse("asset_list"))