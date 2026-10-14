from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Department, User

DEPARTMENTS = ["Administración", "Recursos Humanos", "Contabilidad", "Sistemas", "Ventas"]

# (usuario, nombre, apellido, rol, departamento, puesto)
USERS = [
    ("admin.demo", "Laura", "Díaz", "admin", "Sistemas", "Administradora de TI"),
    ("mario.mata", "Mario", "Mata", "tech", "Sistemas", "Técnico de soporte"),
    ("ana.lopez", "Ana", "López", "tech", "Sistemas", "Técnica de redes"),
    ("juan.perez", "Juan", "Pérez", "user", "Recursos Humanos", "Analista de RH"),
    ("sofia.ramos", "Sofía", "Ramos", "user", "Contabilidad", "Contadora"),
]


class Command(BaseCommand):
    help = "Crea departamentos y usuarios de demostración (solo con DEBUG=True). Se puede repetir sin duplicar."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Demo12345!", help="Contraseña de los usuarios demo")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DEBUG=True.")

        departments = {}
        for name in DEPARTMENTS:
            departments[name], _ = Department.objects.get_or_create(name=name)

        created = 0
        for username, first, last, role, dept, title in USERS:
            user, was_created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first, "last_name": last, "role": role,
                    "email": f"{username}@empresa.test", "department": departments[dept],
                    "job_title": title,
                },
            )
            if was_created:
                user.set_password(options["password"])
                user.save()
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {len(departments)} departamentos y {created} usuarios nuevos "
            f"(contrasena: {options['password']})."
        ))