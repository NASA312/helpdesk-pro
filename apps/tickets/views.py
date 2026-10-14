from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DeleteView, DetailView, FormView, ListView

from apps.accounts.models import Department
from apps.catalog.models import Category, Priority
from apps.core.mixins import AdminRequiredMixin, FormPageMixin

from .forms import AssignForm, CommentForm, StatusForm, TicketCreateForm, TicketStaffForm
from .models import Ticket, TicketAttachment
from .services import TicketError, add_comment, assign, change_status, create_ticket, take, update_details

User = get_user_model()
RELATED = ("category", "priority", "requester", "department", "asset", "assigned_to")


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
        p = self.request.GET
        q = p.get("q", "").strip()
        if q:
            cond = (
                Q(title__icontains=q) | Q(requester__first_name__icontains=q)
                | Q(requester__last_name__icontains=q) | Q(asset__code__icontains=q)
            )
            digits = q.upper().removeprefix("TK-").strip()
            if digits.isdigit() and len(digits) <= 9:           # TK-000184 o 184
                cond |= Q(number=int(digits))
            qs = qs.filter(cond)

        status = p.get("status", "")
        if status == "open":
            qs = qs.active()
        elif status in Ticket.Status.values:
            qs = qs.filter(status=status)
        if p.get("priority", "").isdigit():
            qs = qs.filter(priority_id=int(p["priority"]))
        if p.get("category", "").isdigit():
            qs = qs.filter(category_id=int(p["category"]))
        if p.get("department", "").isdigit():
            qs = qs.filter(department_id=int(p["department"]))
        assigned = p.get("assigned", "")
        if assigned == "me":
            qs = qs.filter(assigned_to=self.request.user)
        elif assigned == "none":
            qs = qs.filter(assigned_to__isnull=True)
        elif assigned.isdigit():
            qs = qs.filter(assigned_to_id=int(assigned))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        get = self.request.GET
        params = get.copy()
        params.pop("page", None)
        ctx.update(
            filters={k: get.get(k, "") for k in ("q", "status", "priority", "category", "assigned", "department")},
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