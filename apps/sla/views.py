from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from apps.core.mixins import AdminRequiredMixin, FormPageMixin

from .forms import ScheduleForm
from .models import BusinessSchedule
from .services import recalculate_open_tickets


class ScheduleUpdateView(FormPageMixin, AdminRequiredMixin, UpdateView):
    form_class = ScheduleForm
    template_name = "core/form_page.html"
    success_url = reverse_lazy("priority_list")
    page_title = "Horario laboral del SLA"
    cancel_url_name = "priority_list"

    def get_object(self, queryset=None):
        return BusinessSchedule.get()

    def form_valid(self, form):
        response = super().form_valid(form)
        count = recalculate_open_tickets()
        messages.success(
            self.request, f"Horario guardado. Se recalcularon los plazos de {count} tickets abiertos."
        )
        return response