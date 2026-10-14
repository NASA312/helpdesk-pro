from django.db import transaction
from django.utils import timezone

from .models import AssetAssignment


@transaction.atomic
def sync_assignment(asset, previous_user_id, actor):
    """
    Llama a esto después de guardar un equipo. Si cambió la persona asignada,
    cierra la asignación vigente y abre una nueva. Devuelve True si hubo cambio.
    """
    if previous_user_id == asset.assigned_to_id:
        return False
    now = timezone.now()
    asset.assignments.filter(returned_at__isnull=True).update(returned_at=now)
    if asset.assigned_to_id:
        AssetAssignment.objects.create(
            asset=asset, user_id=asset.assigned_to_id, assigned_by=actor, assigned_at=now
        )
    return True