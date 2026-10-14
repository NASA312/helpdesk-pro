from django.urls import path

from . import views

urlpatterns = [
    path("usuarios/", views.UserListView.as_view(), name="user_list"),
    path("usuarios/nuevo/", views.UserCreateView.as_view(), name="user_create"),
    path("usuarios/<int:pk>/editar/", views.UserUpdateView.as_view(), name="user_update"),

    path("departamentos/", views.DepartmentListView.as_view(), name="department_list"),
    path("departamentos/nuevo/", views.DepartmentCreateView.as_view(), name="department_create"),
    path("departamentos/<int:pk>/editar/", views.DepartmentUpdateView.as_view(), name="department_update"),
    path("departamentos/<int:pk>/eliminar/", views.DepartmentDeleteView.as_view(), name="department_delete"),

    path("perfil/", views.ProfileView.as_view(), name="profile"),
    path("perfil/contrasena/", views.PasswordChangeWithMessage.as_view(), name="password_change"),
]