from django import forms

from apps.core.forms import TailwindFormMixin

from .models import BusinessSchedule


class ScheduleForm(TailwindFormMixin, forms.ModelForm):
    workdays = forms.MultipleChoiceField(
        label="Días laborables", required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(str(n), label) for n, label in BusinessSchedule.DAYS],
    )

    class Meta:
        model = BusinessSchedule
        fields = ("is_24x7", "workdays", "start_time", "end_time")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["workdays"] = [str(n) for n in sorted(self.instance.workday_numbers)]

    def clean_workdays(self):
        return ",".join(sorted(self.cleaned_data["workdays"], key=int))

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("is_24x7"):
            if not cleaned.get("workdays"):
                self.add_error("workdays", "Elige al menos un día laborable.")
            start, end = cleaned.get("start_time"), cleaned.get("end_time")
            if start and end and end <= start:
                self.add_error("end_time", "La hora de fin debe ser posterior a la de inicio.")
        return cleaned