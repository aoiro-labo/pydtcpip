"""IPTV set-top boxes with dedicated recording containers."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.stb import STB


def _matches(description: DeviceDescription) -> bool:
    """
    Match devices exposing the shared IPTV recording-container layout.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the model uses the dedicated IPTV recording container
    """

    model = description.model_name.upper()
    return model.startswith('STREAMCRUISER SMART TV') or model in ('TT01', 'TT02', 'KS-6100')


STB_HIKARITV = Profile(
    name='stb_hikaritv',
    parent=STB,
    matches=_matches,
    is_unverified=True,
    recording_roots=('0/video/rec/all',),
)
