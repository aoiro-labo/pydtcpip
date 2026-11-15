"""Register device-family profiles and select one from a device description."""

import logging

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.generic import GENERIC
from pydtcpip.dlna.profiles.nasne import NASNE
from pydtcpip.dlna.profiles.toshiba import TOSHIBA
from pydtcpip.dlna.profiles.toshiba_regza_tv import TOSHIBA_REGZA_TV


_LOGGER = logging.getLogger(__name__)

# Registered profiles (add new families here)
PROFILES: tuple[Profile, ...] = (
    GENERIC,
    TOSHIBA,
    TOSHIBA_REGZA_TV,
    NASNE,
)


def select_profile(description: DeviceDescription) -> Profile:
    """
    Select the deepest profile matching the device description.
    Devices that match no family use the generic root profile, which implements standard DLNA behavior.

    Args:
        description (DeviceDescription): Recorder device description

    Returns:
        Profile: Selected profile
    """

    matched = [profile for profile in PROFILES if profile.is_match(description) is True]
    deepest_depth = max(profile.depth for profile in matched)
    deepest = [profile for profile in matched if profile.depth == deepest_depth]

    # Two matches at the same depth indicate overlapping conditions, which tests should catch
    ## At runtime use the first registered profile and log the choice
    if len(deepest) > 1:
        names = ', '.join(profile.name for profile in deepest)
        _LOGGER.warning(
            f'Device description matches multiple profiles at the same depth ({names}); using {deepest[0].name}.'
        )
    return deepest[0]


__all__ = ['GENERIC', 'PROFILES', 'Profile', 'select_profile']
