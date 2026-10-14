import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

from apps.accounts.models import Department, User

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.user.is_helpdesk_admin:
            ctx["active_users"] = User.objects.filter(is_active=True).count()
            ctx["technicians"] = User.objects.filter(role=User.Role.TECH, is_active=True).count()
            ctx["departments"] = Department.objects.filter(is_active=True).count()
        return ctx


@never_cache
@require_safe
def health(request):
    """Para monitores externos y para el healthcheck de Docker."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("Health check: la base de datos no responde")
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})