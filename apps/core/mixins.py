from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


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