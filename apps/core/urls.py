from django.urls import path

from .views import DashboardView, health

urlpatterns = [
    path("salud/", health, name="health"),
    path("", DashboardView.as_view(), name="dashboard"),
]