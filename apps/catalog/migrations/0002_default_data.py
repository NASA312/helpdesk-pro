from django.db import migrations

PRIORITIES = [
    # (nivel, nombre, color, respuesta en min, resolución en min)
    (4, "Crítica", "red", 15, 120),
    (3, "Alta", "orange", 30, 240),
    (2, "Media", "yellow", 120, 480),
    (1, "Baja", "green", 480, 1440),
]

CATEGORIES = [
    ("Redes", "Internet, Wi-Fi, VPN y conectividad"),
    ("Hardware", "Computadoras, monitores y periféricos"),
    ("Software", "Instalación y errores de programas"),
    ("Correo", "Cuentas y problemas de correo"),
    ("Impresoras", "Impresión y escáner"),
    ("Accesos y cuentas", "Contraseñas y permisos"),
    ("Otros", "Cualquier otra solicitud"),
]


def load_defaults(apps, schema_editor):
    Priority = apps.get_model("catalog", "Priority")
    Category = apps.get_model("catalog", "Category")
    for level, name, color, response, resolution in PRIORITIES:
        Priority.objects.get_or_create(
            level=level,
            defaults={"name": name, "color": color, "response_minutes": response, "resolution_minutes": resolution},
        )
    for name, description in CATEGORIES:
        Category.objects.get_or_create(name=name, defaults={"description": description})


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(load_defaults, migrations.RunPython.noop)]