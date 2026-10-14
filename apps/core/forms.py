from django import forms

INPUT_CLASSES = (
    "w-full border border-slate-300 rounded-lg px-3 py-2 text-sm "
    "focus:outline-none focus:ring-2 focus:ring-blue-500"
)


class TailwindFormMixin:
    """Aplica las clases de Tailwind a todos los campos del formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxSelectMultiple):
                continue
            css = "h-4 w-4 rounded" if isinstance(widget, forms.CheckboxInput) else INPUT_CLASSES
            widget.attrs["class"] = f'{widget.attrs.get("class", "")} {css}'.strip()