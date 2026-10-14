from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.urls import reverse


class RoleRequiredMixin(LoginRequiredMixin):
    """Exige sesión iniciada y uno de los roles de `allowed_roles`. Los superusuarios siempre pasan."""
    allowed_roles = ()

    def user_has_role(self, user):
        return user.is_superuser or user.role in self.allowed_roles

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not self.user_has_role(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin",)


class SupportStaffRequiredMixin(RoleRequiredMixin):
    """Administradores y técnicos."""
    allowed_roles = ("admin", "tech")


class FormPageMixin:
    """Da título, enlace de cancelar y aviso a las plantillas genéricas form_page y confirm_delete."""
    page_title = ""
    cancel_url_name = ""
    warning = ""

    def get_page_title(self):
        return self.page_title

    def get_cancel_url(self):
        return reverse(self.cancel_url_name)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(page_title=self.get_page_title(), cancel_url=self.get_cancel_url(), warning=self.warning)
        return ctx