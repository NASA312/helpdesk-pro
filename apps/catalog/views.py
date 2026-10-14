from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import ProtectedError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.core.mixins import AdminRequiredMixin, FormPageMixin

from .forms import CategoryForm, PriorityForm
from .models import Category, Priority

FORM_TEMPLATE = "core/form_page.html"


# ---------------- Categorías ----------------

class CategoryListView(AdminRequiredMixin, ListView):
    model = Category
    template_name = "catalog/category_list.html"
    context_object_name = "categories"


class CategoryCreateView(SuccessMessageMixin, FormPageMixin, AdminRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = FORM_TEMPLATE
    success_url = reverse_lazy("category_list")
    success_message = "Categoría creada."
    page_title = "Nueva categoría"
    cancel_url_name = "category_list"


class CategoryUpdateView(SuccessMessageMixin, FormPageMixin, AdminRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = FORM_TEMPLATE
    success_url = reverse_lazy("category_list")
    success_message = "Categoría actualizada."
    page_title = "Editar categoría"
    cancel_url_name = "category_list"


class CategoryDeleteView(FormPageMixin, AdminRequiredMixin, DeleteView):
    model = Category
    template_name = "core/confirm_delete.html"
    success_url = reverse_lazy("category_list")
    page_title = "Eliminar categoría"
    cancel_url_name = "category_list"
    warning = "Si ya tiene tickets no se podrá eliminar; en ese caso, desactívala."

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, "No se puede eliminar: tiene tickets asociados. Desactívala en su lugar.")
            return redirect("category_list")
        messages.success(self.request, "Categoría eliminada.")
        return response


# ---------------- Prioridades (no se eliminan: se desactivan) ----------------

class PriorityListView(AdminRequiredMixin, ListView):
    model = Priority
    template_name = "catalog/priority_list.html"
    context_object_name = "priorities"


class PriorityCreateView(SuccessMessageMixin, FormPageMixin, AdminRequiredMixin, CreateView):
    model = Priority
    form_class = PriorityForm
    template_name = FORM_TEMPLATE
    success_url = reverse_lazy("priority_list")
    success_message = "Prioridad creada."
    page_title = "Nueva prioridad"
    cancel_url_name = "priority_list"


class PriorityUpdateView(SuccessMessageMixin, FormPageMixin, AdminRequiredMixin, UpdateView):
    model = Priority
    form_class = PriorityForm
    template_name = FORM_TEMPLATE
    success_url = reverse_lazy("priority_list")
    success_message = "Prioridad actualizada."
    page_title = "Editar prioridad"
    cancel_url_name = "priority_list"