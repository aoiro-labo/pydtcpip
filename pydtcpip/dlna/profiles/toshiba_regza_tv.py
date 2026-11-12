"""Toshiba REGZA TV profile, derived from the Toshiba profile."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.toshiba import TOSHIBA


def _matches(description: DeviceDescription) -> bool:
    """
    Match a REGZA television's manufacturer name.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: True when the manufacturer contains REGZA
    """

    # REGZA TVs report `TOSHIBA TVS REGZA` as the manufacturer (recorders report only `TOSHIBA`)
    return 'REGZA' in description.manufacturer.upper()


TOSHIBA_REGZA_TV = Profile(
    name='toshiba_regza_tv',
    parent=TOSHIBA,
    matches=_matches,
    # REGZA 43Z570L includes broadcast network and service IDs (regza:network_id and regza:service_id)
    # only in BrowseDirectChildren responses, not in BrowseMetadata responses
    has_listing_only_metadata=True,
)
