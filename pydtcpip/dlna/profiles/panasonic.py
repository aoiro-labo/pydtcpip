"""Profile for Panasonic recorders."""

from xml.etree import ElementTree as ET

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.generic import GENERIC
from pydtcpip.models import ProtectionValue


# pxn:CopyCount is an attribute of the res element, so read it in the DIDL-Lite namespace
_DIDL_NAMESPACE = 'urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/'
_PXN_NAMESPACES = ('urn:schemas-panasonic-com:pxn',)


def _matches(description: DeviceDescription) -> bool:
    """
    Match Panasonic manufacturer names.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: True when the manufacturer contains Panasonic
    """

    return 'PANASONIC' in description.manufacturer.upper()


def _read_remaining_copy_count(item: ET.Element) -> ProtectionValue[int]:
    """
    Read pxn:CopyCount from the res elements, excluding the final Move from the result.

    Args:
        item (ET.Element): Recording's DIDL-Lite item

    Returns:
        ProtectionValue[int]: Copy count and its acquisition status
    """

    # Only the resource in the stored format carries the attribute, while converted resources omit it
    ## Read every value so that a disagreement between resources is reported rather than silently resolved
    values: set[str] = set()
    for resource in item.findall(f'{{{_DIDL_NAMESPACE}}}res'):
        for namespace in _PXN_NAMESPACES:
            value = resource.get(f'{{{namespace}}}CopyCount')
            if value is not None:
                values.add(value.strip())

    # The element is absent from BrowseMetadata responses and from recordings the device does not count
    if len(values) == 0:
        return ProtectionValue[int](status='omitted', source='metadata')
    if len(values) > 1:
        return ProtectionValue[int](status='unsupported', source='metadata')

    value = values.pop()
    # CopyCount counts every permitted copy including the final Move, so a recording starts at 10
    # and the displayed count, which excludes the final Move, is one less; zero has not been observed
    if value.isdecimal() is False or int(value) == 0:
        return ProtectionValue[int](status='unsupported', source='metadata')
    return ProtectionValue[int](status='known', value=int(value) - 1, source='metadata')


PANASONIC = Profile(
    name='panasonic',
    parent=GENERIC,
    matches=_matches,
    read_remaining_copy_count=_read_remaining_copy_count,
    # CopyCount appears only in BrowseDirectChildren, so read recordings from their parent listing
    has_listing_only_metadata=True,
)
