"""STW2000 recording discovery and shared-tag chapters."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.stb import STB


def _matches(description: DeviceDescription) -> bool:
    """
    Identify the STW2000 family.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the advertised model is STW2000
    """

    return description.model_name.upper() == 'STW2000'


STB_STW2000 = Profile(
    name='stb_stw2000',
    parent=STB,
    matches=_matches,
    is_unverified=True,
    recording_roots=('0/rec/all',),
)
