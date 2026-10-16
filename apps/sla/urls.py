from django.urls import path

from . import views

urlpatterns = [
    path("sla/horario/", views.ScheduleUpdateView.as_view(), name="sla_schedule"),
]