from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Department, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("HelpDesk", {"fields": ("role", "department", "job_title", "phone")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Datos", {"fields": ("email", "first_name", "last_name", "role", "department")}),
    )
    list_display = ("username", "email", "role", "department", "is_active")
    list_filter = ("role", "department", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)