from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.assets.models import Asset
from apps.catalog.models import Category, Priority
from apps.tickets.models import Ticket
from apps.tickets.services import add_comment, assign, change_status, create_ticket

DEMO_USERS = ["admin.demo", "mario.mata", "ana.lopez", "juan.perez", "sofia.ramos"]


class Command(BaseCommand):
    help = "Crea tickets de demostración en distintos estados (solo con DEBUG=True). Requiere seed_demo."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DEBUG=True.")
        people = {u.username: u for u in User.objects.filter(username__in=DEMO_USERS)}
        if len(people) < len(DEMO_USERS):
            raise CommandError("Faltan los usuarios demo. Ejecuta primero: python manage.py seed_demo")
        if Ticket.objects.exists():
            self.stdout.write("Ya existen tickets: no se crea nada.")
            return

        cat = {c.name: c for c in Category.objects.all()}
        prio = {p.level: p for p in Priority.objects.all()}
        admin, mario, ana = people["admin.demo"], people["mario.mata"], people["ana.lopez"]
        juan, sofia = people["juan.perez"], people["sofia.ramos"]
        pc = Asset.objects.alive().filter(code="PC-RH-023").first()

        # 1) Nuevo, sin asignar
        create_ticket(
            creator=juan, requester=juan, title="Computadora sin conexión a Internet",
            description="Desde la mañana mi computadora no tiene Internet. El cable está conectado.",
            category=cat["Redes"], priority=prio[3], asset=pc,
        )
        # 2) Asignado
        t = create_ticket(
            creator=sofia, requester=sofia, title="La impresora no imprime",
            description="Se queda en cola y no sale nada.", category=cat["Impresoras"], priority=prio[2],
        )
        assign(t, admin, mario)
        # 3) Esperando usuario
        t = create_ticket(
            creator=sofia, requester=sofia, title="No puedo abrir mi correo",
            description="Outlook pide la contraseña una y otra vez.", category=cat["Correo"], priority=prio[2],
        )
        assign(t, admin, ana)
        change_status(t, ana, "in_progress")
        add_comment(t, ana, "¿Qué mensaje de error te aparece exactamente?")
        change_status(t, ana, "waiting_user")
        # 4) Resuelto
        t = create_ticket(
            creator=juan, requester=juan, title="Instalar Office en equipo nuevo",
            description="Necesito Word y Excel en mi computadora.", category=cat["Software"], priority=prio[1],
        )
        assign(t, admin, mario)
        change_status(t, mario, "in_progress")
        add_comment(t, mario, "Se requiere licencia, ya la tengo.", internal=True)
        change_status(t, mario, "resolved", "Se instaló Office y se activó con la licencia de la empresa.")
        # 5) Crítico, sin asignar
        create_ticket(
            creator=juan, requester=juan, title="La VPN no conecta desde casa",
            description="Necesito entrar al sistema de nómina y la VPN falla.",
            category=cat["Redes"], priority=prio[4],
        )

        self.stdout.write(self.style.SUCCESS("Listo: 5 tickets de demostración."))