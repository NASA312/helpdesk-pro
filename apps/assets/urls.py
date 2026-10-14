from django.urls import path

from . import views

urlpatterns = [
    path("equipos/", views.AssetListView.as_view(), name="asset_list"),
    path("equipos/nuevo/", views.AssetCreateView.as_view(), name="asset_create"),
    path("equipos/<int:pk>/", views.AssetDetailView.as_view(), name="asset_detail"),
    path("equipos/<int:pk>/editar/", views.AssetUpdateView.as_view(), name="asset_update"),
    path("equipos/<int:pk>/eliminar/", views.AssetDeleteView.as_view(), name="asset_delete"),
    path("mis-equipos/", views.MyAssetsView.as_view(), name="my_assets"),
]