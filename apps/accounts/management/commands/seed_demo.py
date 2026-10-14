from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.assets.models import Asset
from apps.assets.services import sync_assignment

DEPARTMENTS = ["Administración", "Recursos Humanos", "Contabilidad", "Sistemas", "Ventas"]

# (usuario, nombre, apellido, rol, departamento, puesto)
USERS = [
    ("admin.demo", "Laura", "Díaz", "admin", "Sistemas", "Administradora de TI"),
    ("mario.mata", "Mario", "Mata", "tech", "Sistemas", "Técnico de soporte"),
    ("ana.lopez", "Ana", "López", "tech", "Sistemas", "Técnica de redes"),
    ("juan.perez", "Juan", "Pérez", "user", "Recursos Humanos", "Analista de RH"),
    ("sofia.ramos", "Sofía", "Ramos", "user", "Contabilidad", "Contadora"),
]

# (código, tipo, marca, modelo, serie, ip, sistema, estado, persona, departamento, días de garantía restantes)
ASSETS = [
    ("PC-RH-023", "computer", "Dell", "OptiPlex 7090", "SN-DL7090-023", "192.168.1.43", "Windows 11", "active", "juan.perez", "Recursos Humanos", 400),
    ("PC-CT-011", "computer", "HP", "ProDesk 400 G7", "SN-HP400-011", "192.168.1.57", "Windows 11", "active", "sofia.ramos", "Contabilidad", 20),
    ("LT-SIS-004", "laptop", "Lenovo", "ThinkPad T14", "SN-LT14-004", "192.168.1.88", "Windows 11", "active", "mario.mata", "Sistemas", 700),
    ("IMP-RH-002", "printer", "Brother", "HL-L5100DN", "SN-BR5100-002", "192.168.1.120", "", "active", None, "Recursos Humanos", -60),
    ("SW-SIS-001", "network", "Cisco", "Catalyst 2960", "SN-CS2960-001", "192.168.1.2", "Cisco IOS", "active", None, "Sistemas", 900),
    ("PC-VT-009", "computer", "Dell", "OptiPlex 3080", "SN-DL3080-009", "", "Windows 10", "repair", None, "Ventas", -200),
]


class Command(BaseCommand):
    help = "Crea departamentos, usuarios y equipos de demostración (solo con DEBUG=True). Se puede repetir sin duplicar."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Demo12345!", help="Contraseña de los usuarios demo")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DEBUG=True.")

        departments = {}
        for name in DEPARTMENTS:
            departments[name], _ = Department.objects.get_or_create(name=name)

        people, created = {}, 0
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
            people[username] = user

        today = timezone.localdate()
        new_assets = 0
        for code, kind, brand, model, serial, ip, os_name, status, owner, dept, warranty in ASSETS:
            if Asset.objects.alive().filter(code=code).exists():
                continue
            asset = Asset.objects.create(
                code=code, asset_type=kind, brand=brand, model=model, serial_number=serial,
                ip_address=ip or None, operating_system=os_name, status=status,
                assigned_to=people.get(owner), department=departments[dept],
                purchase_date=today - timedelta(days=730),
                warranty_until=today + timedelta(days=warranty),
            )
            sync_assignment(asset, None, people["admin.demo"])
            new_assets += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {len(departments)} departamentos, {created} usuarios nuevos y {new_assets} equipos nuevos "
            f"(contrasena: {options['password']})."
        ))