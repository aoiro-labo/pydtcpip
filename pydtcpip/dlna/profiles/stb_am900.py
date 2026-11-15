"""AM900 recording-container layout."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.stb import STB


def _matches(description: DeviceDescription) -> bool:
    """
    Identify the AM900 within the set-top box family.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the device advertises the AM900 model
    """

    return description.model_name.upper() == 'AM900'


STB_AM900 = Profile(
    name='stb_am900',
    parent=STB,
    matches=_matches,
    is_unverified=True,
    recording_roots=('0-0-0-0',),
)
