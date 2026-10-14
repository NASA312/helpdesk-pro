from django.urls import path

from . import views

urlpatterns = [
    path("tickets/", views.TicketListView.as_view(), name="ticket_list"),
    path("tickets/nuevo/", views.TicketCreateView.as_view(), name="ticket_create"),
    path("tickets/<int:pk>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("tickets/<int:pk>/editar/", views.TicketEditView.as_view(), name="ticket_edit"),
    path("tickets/<int:pk>/eliminar/", views.TicketDeleteView.as_view(), name="ticket_delete"),
    path("tickets/<int:pk>/tomar/", views.TicketTakeView.as_view(), name="ticket_take"),
    path("tickets/<int:pk>/asignar/", views.TicketAssignView.as_view(), name="ticket_assign"),
    path("tickets/<int:pk>/estado/", views.TicketStatusView.as_view(), name="ticket_status"),
    path("tickets/<int:pk>/comentar/", views.TicketCommentView.as_view(), name="ticket_comment"),
    path("tickets/<int:pk>/adjuntos/<int:attachment_pk>/", views.TicketAttachmentView.as_view(), name="ticket_attachment"),
]