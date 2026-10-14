from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketComment, TicketEvent


class CommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0


class EventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    can_delete = False
    readonly_fields = ("actor", "kind", "message", "is_internal", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "status", "priority", "requester", "assigned_to", "created_at", "deleted_at")
    list_filter = ("status", "priority", "category")
    search_fields = ("title", "requester__username", "requester__email")
    readonly_fields = ("number",)
    inlines = [CommentInline, EventInline]

    def has_add_permission(self, request):
        return False        # los tickets se crean desde la aplicación (así reciben su número)


admin.site.register(TicketAttachment)