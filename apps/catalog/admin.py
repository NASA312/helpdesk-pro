from django.contrib import admin

from .models import Category, Priority


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)


@admin.register(Priority)
class PriorityAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "response_minutes", "resolution_minutes", "is_active")