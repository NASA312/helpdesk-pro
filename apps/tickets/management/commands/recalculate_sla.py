from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.sla.services import apply_deadlines, get_calendar
from apps.tickets.models import Ticket

S = Ticket.Status


class Command(BaseCommand):
    help = "Calcula los plazos del SLA de los tickets abiertos o que aún no los tienen. Usa --all para todos."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Recalcula también los tickets resueltos y cerrados")

    def handle(self, *args, **options):
        qs = Ticket.objects.alive().select_related("priority")
        if not options["all"]:
            qs = qs.filter(
                Q(response_due_at__isnull=True) | Q(resolution_due_at__isnull=True)
                | Q(status__in=[S.NEW, S.ASSIGNED, S.IN_PROGRESS, S.WAITING_USER])
            )
        cal, now, count = get_calendar(), timezone.now(), 0
        for ticket in qs:
            if ticket.status == S.WAITING_USER and ticket.sla_paused_at is None:
                ticket.sla_paused_at = now                      # la pausa empieza ahora
            apply_deadlines(ticket, cal)
            ticket.save(update_fields=["response_due_at", "resolution_due_at", "sla_paused_at"])
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Listo: {count} tickets recalculados."))