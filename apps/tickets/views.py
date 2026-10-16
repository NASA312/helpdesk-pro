from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DeleteView, DetailView, FormView, ListView, TemplateView

from apps.accounts.models import Department
from apps.catalog.models import Category, Priority
from apps.core.mixins import AdminRequiredMixin, FormPageMixin, SupportStaffRequiredMixin
from apps.sla.services import evaluate, get_calendar

from .filters import apply_filters
from .forms import AssignForm, CommentForm, StatusForm, TicketCreateForm, TicketStaffForm
from .models import Ticket, TicketAttachment
from .services import (
    NoteRequired, TicketError, add_comment, assign, board_move, change_status,
    create_ticket, take, update_details,
)

User = get_user_model()
RELATED = ("category", "priority", "requester", "department", "asset", "assigned_to")
BOARD_RELATED = ("category", "priority", "requester", "assigned_to", "asset")
BOARD_CLOSED_DAYS = 7


def get_ticket(user, pk):
    """Ticket visible para `user`. Si no puede verlo: 404 (no se revela que existe)."""
    return get_object_or_404(Ticket.objects.for_user(user).select_related(*RELATED), pk=pk)


def form_errors(form):
    return " ".join(message for errors in form.errors.values() for message in errors)


# ---------------- Listado ----------------

class TicketListView(LoginRequiredMixin, ListView):
    template_name = "tickets/ticket_list.html"
    context_object_name = "tickets"
    paginate_by = 20

    def get_queryset(self):
        qs = Ticket.objects.for_user(self.request.user).select_related(
            "category", "priority", "requester", "assigned_to", "asset"
        )
        return apply_filters(qs, self.request.GET, self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user, get = self.request.user, self.request.GET
        params = get.copy()
        params.pop("page", None)

        tickets = list(ctx["tickets"])
        if user.is_support_staff:
            cal, now = get_calendar(), timezone.now()
            for t in tickets:
                t.sla = evaluate(t, cal, now)
        ctx["tickets"] = tickets

        ctx.update(
            filters={k: get.get(k, "") for k in ("q", "status", "priority", "category", "assigned", "department", "sla")},
            statuses=[("open", "Abiertos (sin resolver)")] + list(Ticket.Status.choices),
            priorities=Priority.objects.all(),
            categories=Category.objects.all(),
            departments=Department.objects.all(),
            staff_members=User.objects.filter(is_active=True, role__in=[User.Role.ADMIN, User.Role.TECH]),
            extra=("&" + params.urlencode()) if params else "",
        )
        return ctx

# ---------------- Crear ----------------

class TicketCreateView(LoginRequiredMixin, FormView):
    template_name = "tickets/ticket_form.html"
    form_class = TicketCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        user, data = self.request.user, form.cleaned_data
        ticket = create_ticket(
            creator=user,
            requester=data.get("requester") or user,
            title=data["title"], description=data["description"],
            category=data["category"], priority=data["priority"],
            asset=data.get("asset"), file=data.get("file"),
        )
        messages.success(self.request, f"Ticket {ticket.code} creado. Puedes seguir su avance desde esta página.")
        return redirect(ticket)


# ---------------- Detalle ----------------

class TicketDetailView(LoginRequiredMixin, DetailView):
    template_name = "tickets/ticket_detail.html"
    context_object_name = "ticket"

    def get_queryset(self):
        return Ticket.objects.for_user(self.request.user).select_related(*RELATED)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        t, user = self.object, self.request.user
        see_internal = t.user_can_see_internal(user)

        comments = t.comments.select_related("author").prefetch_related(
            Prefetch("attachments", queryset=t.attachments.all())
        )
        events = t.events.select_related("actor")
        if not see_internal:
            comments = comments.filter(is_internal=False)
            events = events.filter(is_internal=False)

        ctx.update(
            comments=comments,
            events=events,
            initial_attachments=t.attachments.filter(comment__isnull=True),
            see_internal=see_internal,
            can_edit=t.user_can_work(user) and t.status != Ticket.Status.CLOSED,
            can_take=t.user_can_take(user),
            assign_form=AssignForm(ticket=t) if t.user_can_assign(user) else None,
            status_form=StatusForm(ticket=t, user=user) if t.allowed_transitions(user) else None,
            comment_form=CommentForm(can_internal=see_internal) if t.user_can_comment(user) else None,
            sla=evaluate(t),
        )
        return ctx


# ---------------- Editar categoría, prioridad y equipo (soporte) ----------------

class TicketEditView(FormPageMixin, LoginRequiredMixin, FormView):
    form_class = TicketStaffForm
    template_name = "core/form_page.html"

    @cached_property
    def ticket(self):
        ticket = get_ticket(self.request.user, self.kwargs["pk"])
        if not ticket.user_can_work(self.request.user) or ticket.status == Ticket.Status.CLOSED:
            raise PermissionDenied
        return ticket

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.ticket
        return kwargs

    def get_page_title(self):
        return f"Editar {self.ticket.code}"

    def get_cancel_url(self):
        return self.ticket.get_absolute_url()

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            changed = update_details(
                self.ticket, self.request.user,
                category=data["category"], priority=data["priority"], asset=data.get("asset"),
            )
        except TicketError as exc:
            messages.error(self.request, exc.message)
        else:
            messages.success(self.request, "Ticket actualizado." if changed else "No hubo cambios.")
        return redirect(self.ticket)


class TicketDeleteView(FormPageMixin, AdminRequiredMixin, DeleteView):
    template_name = "core/confirm_delete.html"
    page_title = "Eliminar ticket"
    warning = "Dejará de mostrarse, pero se conserva su historial en la base de datos."

    def get_queryset(self):
        return Ticket.objects.alive()

    def get_cancel_url(self):
        return self.object.get_absolute_url()

    def form_valid(self, form):
        self.object.soft_delete()
        messages.success(self.request, "Ticket eliminado.")
        return HttpResponseRedirect(reverse("ticket_list"))


# ---------------- Acciones (POST) ----------------

def _finish(request, ticket):
    """Si la persona ya no puede ver el ticket (p. ej. lo reasignó), la manda al listado."""
    if Ticket.objects.for_user(request.user).filter(pk=ticket.pk).exists():
        return redirect(ticket)
    return redirect("ticket_list")


class TicketActionView(LoginRequiredMixin, View):
    http_method_names = ["post"]


class TicketTakeView(TicketActionView):
    def post(self, request, pk):
        ticket = get_ticket(request.user, pk)
        try:
            take(ticket, request.user)
        except TicketError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, f"Tomaste el ticket {ticket.code}.")
        return _finish(request, ticket)


class TicketAssignView(TicketActionView):
    def post(self, request, pk):
        ticket = get_ticket(request.user, pk)
        form = AssignForm(request.POST, ticket=ticket)
        if not form.is_valid():
            messages.error(request, "Elige a una persona del equipo de soporte.")
            return redirect(ticket)
        try:
            assign(ticket, request.user, form.cleaned_data["assignee"])
        except TicketError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "Ticket asignado.")
        return _finish(request, ticket)


class TicketStatusView(TicketActionView):
    def post(self, request, pk):
        ticket = get_ticket(request.user, pk)
        form = StatusForm(request.POST, ticket=ticket, user=request.user)
        if not form.is_valid():
            messages.error(request, form_errors(form) or "Cambio de estado no válido.")
            return redirect(ticket)
        try:
            change_status(ticket, request.user, form.cleaned_data["status"], form.cleaned_data["note"])
        except TicketError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "Estado actualizado.")
        return _finish(request, ticket)


class TicketCommentView(TicketActionView):
    def post(self, request, pk):
        ticket = get_ticket(request.user, pk)
        form = CommentForm(
            request.POST, request.FILES, can_internal=ticket.user_can_see_internal(request.user)
        )
        if not form.is_valid():
            messages.error(request, form_errors(form) or "Mensaje no válido.")
            return redirect(ticket)
        data = form.cleaned_data
        try:
            add_comment(
                ticket, request.user, data["body"],
                internal=data.get("is_internal", False), file=data.get("file"),
            )
        except TicketError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "Nota interna guardada." if data.get("is_internal") else "Comentario enviado.")
        return redirect(ticket)


class TicketAttachmentView(LoginRequiredMixin, View):
    """Descarga protegida: solo quien puede ver el ticket y ese adjunto."""

    def get(self, request, pk, attachment_pk):
        ticket = get_ticket(request.user, pk)
        attachments = ticket.attachments.all()
        if not ticket.user_can_see_internal(request.user):
            attachments = attachments.filter(Q(comment__isnull=True) | Q(comment__is_internal=False))
        attachment = get_object_or_404(attachments, pk=attachment_pk)
        try:
            handle = attachment.file.open("rb")
        except FileNotFoundError:
            raise Http404("El archivo ya no está disponible.")
        return FileResponse(handle, as_attachment=True, filename=attachment.filename)
    
# ---------------- SLA y tablero ----------------

class TicketSLAView(LoginRequiredMixin, View):
    """Fragmento HTMX con el reloj del SLA (la página lo consulta cada 60 s)."""

    def get(self, request, pk):
        ticket = get_ticket(request.user, pk)
        return render(request, "sla/partials/panel.html", {"ticket": ticket, "sla": evaluate(ticket)})


class TicketBoardView(SupportStaffRequiredMixin, TemplateView):
    template_name = "tickets/board.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user, get = self.request.user, self.request.GET
        cutoff = timezone.now() - timedelta(days=BOARD_CLOSED_DAYS)

        qs = (
            Ticket.objects.for_user(user).select_related(*BOARD_RELATED)
            .exclude(status=Ticket.Status.CLOSED, closed_at__lt=cutoff)      # cerrados: solo la última semana
            .order_by("-priority__level", "created_at")
        )
        qs = apply_filters(qs, get, user, include_status=False)

        cal, now = get_calendar(), timezone.now()
        columns = {value: [] for value in Ticket.Status.values}
        for t in qs:
            t.sla = evaluate(t, cal, now)
            t.movable = t.user_can_work(user) or t.user_can_take(user)
            columns[t.status].append(t)

        filters = {k: get.get(k, "") for k in ("q", "assigned", "priority", "category")}
        ctx.update(
            columns=[(value, label, columns[value]) for value, label in Ticket.Status.choices],
            filters=filters,
            has_filters=any(filters.values()),
            priorities=Priority.objects.all(),
            categories=Category.objects.all(),
            staff_members=User.objects.filter(is_active=True, role__in=[User.Role.ADMIN, User.Role.TECH]),
            closed_days=BOARD_CLOSED_DAYS,
        )
        return ctx


class TicketBoardMoveView(SupportStaffRequiredMixin, View):
    """Lo llama el arrastrar y soltar. Responde JSON con la tarjeta ya actualizada."""
    http_method_names = ["post"]

    def post(self, request, pk):
        ticket = get_ticket(request.user, pk)                 # 404 si no puede verlo
        try:
            board_move(ticket, request.user, request.POST.get("status", ""), request.POST.get("note", ""))
        except NoteRequired as exc:
            return JsonResponse({"needs_note": True, "message": exc.message}, status=422)
        except TicketError as exc:
            return JsonResponse({"error": exc.message}, status=409)

        t = Ticket.objects.select_related(*BOARD_RELATED).get(pk=ticket.pk)
        t.sla = evaluate(t)
        t.movable = t.user_can_work(request.user) or t.user_can_take(request.user)
        return JsonResponse({"ok": True, "html": render_to_string("tickets/partials/board_card.html", {"t": t})})