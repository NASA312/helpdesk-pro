from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models


class Department(models.Model):
    name = models.CharField("Nombre", max_length=100, unique=True)
    description = models.TextField("Descripción", blank=True)
    is_active = models.BooleanField("Activo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Un superusuario siempre nace como administrador (evita el problema de "usuario sin rol")
        extra_fields.setdefault("role", self.model.Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        TECH = "tech", "Técnico"
        USER = "user", "Usuario"

    email = models.EmailField("Correo electrónico", unique=True)
    role = models.CharField("Rol", max_length=10, choices=Role.choices, default=Role.USER)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT,
        related_name="users", verbose_name="Departamento",
    )
    job_title = models.CharField("Puesto", max_length=100, blank=True)
    phone = models.CharField("Teléfono", max_length=30, blank=True)

    objects = UserManager()

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def is_helpdesk_admin(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def is_technician(self):
        return self.role == self.Role.TECH

    @property
    def is_support_staff(self):
        """Administradores y técnicos (quienes atienden tickets)."""
        return self.is_helpdesk_admin or self.is_technician