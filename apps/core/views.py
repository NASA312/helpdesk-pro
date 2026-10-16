import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView
from apps.assets.models import Asset
from apps.tickets.models import Ticket

from apps.accounts.models import Department, User

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        assets = Asset.objects.alive()
        tickets = Ticket.objects.for_user(user)
        S = Ticket.Status

        if user.is_helpdesk_admin:
            ctx["active_users"] = User.objects.filter(is_active=True).count()
            ctx["technicians"] = User.objects.filter(role=User.Role.TECH, is_active=True).count()
            ctx["departments"] = Department.objects.filter(is_active=True).count()

        if user.is_support_staff:
            in_use = assets.exclude(status=Asset.Status.RETIRED)
            ctx["assets_total"] = in_use.count()
            ctx["assets_repair"] = assets.filter(status=Asset.Status.REPAIR).count()
            ctx["assets_unassigned"] = in_use.filter(assigned_to__isnull=True).count()
            ctx["tickets_unassigned"] = tickets.filter(status=S.NEW, assigned_to__isnull=True).count()
            ctx["tickets_mine"] = tickets.active().filter(assigned_to=user).count()
            ctx["tickets_breached"] = tickets.sla_breached().count()
        else:
            ctx["my_assets_count"] = assets.filter(assigned_to=user).count()
            ctx["tickets_waiting"] = tickets.filter(status=S.WAITING_USER).count()

        ctx["tickets_open"] = tickets.active().count()
        ctx["recent_tickets"] = tickets.select_related("priority").order_by("-created_at")[:5]
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