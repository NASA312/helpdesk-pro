from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".sh", ".ps1", ".vbs", ".jar", ".js", ".hta",
}


def validate_upload(file):
    """Tamaño máximo y extensiones peligrosas. Se usa en todos los formularios con archivos."""
    max_mb = settings.MAX_UPLOAD_MB
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"El archivo supera el máximo de {max_mb} MB.")
    if Path(file.name).suffix.lower() in BLOCKED_EXTENSIONS:
        raise ValidationError("Este tipo de archivo no está permitido.")