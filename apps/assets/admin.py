from django.contrib import admin

from .models import Asset, AssetAssignment


class AssignmentInline(admin.TabularInline):
    model = AssetAssignment
    extra = 0
    fk_name = "asset"


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("code", "asset_type", "brand", "model", "status", "assigned_to", "deleted_at")
    list_filter = ("asset_type", "status", "department")
    search_fields = ("code", "brand", "model", "serial_number", "ip_address")
    inlines = [AssignmentInline]