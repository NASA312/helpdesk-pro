from django.urls import path

from . import views

urlpatterns = [
    path("categorias/", views.CategoryListView.as_view(), name="category_list"),
    path("categorias/nueva/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categorias/<int:pk>/editar/", views.CategoryUpdateView.as_view(), name="category_update"),
    path("categorias/<int:pk>/eliminar/", views.CategoryDeleteView.as_view(), name="category_delete"),

    path("prioridades/", views.PriorityListView.as_view(), name="priority_list"),
    path("prioridades/nueva/", views.PriorityCreateView.as_view(), name="priority_create"),
    path("prioridades/<int:pk>/editar/", views.PriorityUpdateView.as_view(), name="priority_update"),
]