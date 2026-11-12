"""Profile for nasne devices sold by SIE."""

from xml.etree import ElementTree as ET

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import Profile
from pydtcpip.dlna.profiles.generic import GENERIC
from pydtcpip.errors import ClientNotAllowedError, PyDTCPIPError
from pydtcpip.models import ProtectionValue


# Namespace of av:COGCount, which reports a recording's remaining copies
_SONY_AV_NAMESPACE = 'urn:schemas-sony-com:av'


def _matches(description: DeviceDescription) -> bool:
    """
    Match the model name reported by SIE's nasne.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: True when the model name is nasne
    """

    # SIE's nasne reports `nasne` as its model name (other vendors use different names)
    return description.model_name.lower() == 'nasne'


def _read_remaining_copy_count(item: ET.Element) -> ProtectionValue[int]:
    """
    Read the remaining copy count from av:COGCount.

    Args:
        item (ET.Element): Recording's DIDL-Lite item

    Returns:
        ProtectionValue[int]: Copy count and its acquisition status
    """

    # av:COGCount contains the remaining copy count as a decimal; recordings without a count omit the element
    ## Whether the count includes the final Move, unlike the common field, has not been verified on a device
    value = item.findtext(f'{{{_SONY_AV_NAMESPACE}}}COGCount')
    if value is None:
        return ProtectionValue[int](status='omitted', source='metadata')
    if value.strip().isdecimal() is False:
        return ProtectionValue[int](status='unsupported', source='metadata')
    return ProtectionValue[int](status='known', value=int(value.strip()), source='metadata')


def _interpret_http_status(status: int, url: str) -> PyDTCPIPError | None:
    """
    Interpret nasne's client authorization refusal.

    Args:
        status (int): HTTP status code
        url (str): URL of the failed request

    Returns:
        PyDTCPIPError | None: Client authorization error for 403, otherwise None
    """

    # nasne returns 403 for listing and media requests from unauthorized media server clients
    if status == 403:
        return ClientNotAllowedError(
            'nasne has not authorized this PC as a client. '
            'Allow this PC under Media Server Settings > Client Device Management in nasne HOME, then try again.',
            http_status=status,
        )
    return None


SIE_NASNE = Profile(
    name='sie_nasne',
    parent=GENERIC,
    matches=_matches,
    read_remaining_copy_count=_read_remaining_copy_count,
    interpret_http_status=_interpret_http_status,
)
