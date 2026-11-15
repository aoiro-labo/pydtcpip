"""I-O DATA REC-ON network recorders."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import CopyCountField, Profile
from pydtcpip.dlna.profiles.generic import GENERIC


def _matches(description: DeviceDescription) -> bool:
    """
    Match REC-ON models with the shared tag service.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the model belongs to this family
    """

    return description.model_name.upper() in ('GV-NTX1', 'GV-NTX2', 'HVTR-BCTX3', 'EX-BCTX2')


RECON = Profile(
    name='recon',
    parent=GENERIC,
    matches=_matches,
    is_unverified=True,
    copy_count_fields=(
        CopyCountField(
            'allowedUse', on_resource=True, is_allowed_use=True, includes_final_move=True, unlimited_values=('-1',)
        ),
    ),
    extension='shared_tags',
)
