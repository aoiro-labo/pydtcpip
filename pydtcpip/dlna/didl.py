"""Convert DIDL-Lite from ContentDirectory Browse into folder and recording models."""

from xml.etree import ElementTree as ET

from pydtcpip.dlna.arib import ARIB_PUA_TO_UNICODE
from pydtcpip.dlna.profiles import Profile
from pydtcpip.dlna.protocol_info import parse_protocol_info
from pydtcpip.errors import DLNAError
from pydtcpip.models import Container, ProtectionValue, Recording, RecordingProtection, Resource


DIDL_NAMESPACE = 'urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/'
UPNP_NAMESPACE = 'urn:schemas-upnp-org:metadata-1-0/upnp/'
DC_NAMESPACE = 'http://purl.org/dc/elements/1.1/'
ARIB_NAMESPACE = 'urn:schemas-arib-or-jp:elements-1-0/'

# DTCP.COM_FLAGS bits (from the most significant: Move and transaction-based Move support)
_DTCP_FLAG_MOVE = 1 << 31
_DTCP_FLAG_TRANSACTION_MOVE = 1 << 30


def parse_didl(raw_xml: str, profile: Profile) -> list[Container | Recording]:
    """
    Parse DIDL-Lite and return folders and recordings in document order.
    The profile interprets recorder-specific elements. Human-readable metadata is normalized from
    ARIB private-use codes to standard Unicode, including the XML retained for sidecar files.

    Args:
        raw_xml (str): DIDL-Lite from the Browse Result
        profile (Profile): Recorder family profile

    Returns:
        list[Container | Recording]: Folders and recordings
    """

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as ex:
        raise DLNAError('Could not parse the recording listing (DIDL-Lite) XML.') from ex

    # Normalize text at the metadata boundary so API values and saved XML agree
    # Resource URLs, identifiers, protection values, and unknown extensions retain their original values
    text_tags = {
        f'{{{DC_NAMESPACE}}}title',
        f'{{{DC_NAMESPACE}}}description',
        f'{{{UPNP_NAMESPACE}}}longDescription',
        f'{{{ARIB_NAMESPACE}}}longDescription',
        f'{{{UPNP_NAMESPACE}}}channelName',
        f'{{{UPNP_NAMESPACE}}}genre',
    }
    for element in root.iter():
        if element.tag in text_tags and element.text is not None:
            element.text = element.text.translate(ARIB_PUA_TO_UNICODE)

    read_remaining_copy_count = profile.resolve_remaining_copy_count()
    objects: list[Container | Recording] = []
    for element in root:
        # Folders contain their child count and class
        if element.tag == f'{{{DIDL_NAMESPACE}}}container':
            child_count = element.get('childCount')
            objects.append(
                Container(
                    id=element.get('id', ''),
                    parent_id=element.get('parentID', ''),
                    title=element.findtext(f'{{{DC_NAMESPACE}}}title') or '',
                    upnp_class=element.findtext(f'{{{UPNP_NAMESPACE}}}class') or '',
                    child_count=int(child_count) if child_count is not None and child_count.isdecimal() else None,
                    raw_xml=ET.tostring(element, encoding='unicode'),
                )
            )

        # Recordings contain program metadata, resources, and protection information
        elif element.tag == f'{{{DIDL_NAMESPACE}}}item':
            resources = tuple(_parse_resource(res) for res in element.iterfind(f'{{{DIDL_NAMESPACE}}}res'))
            objects.append(
                Recording(
                    id=element.get('id', ''),
                    parent_id=element.get('parentID', ''),
                    title=element.findtext(f'{{{DC_NAMESPACE}}}title') or '',
                    upnp_class=element.findtext(f'{{{UPNP_NAMESPACE}}}class') or '',
                    description=element.findtext(f'{{{DC_NAMESPACE}}}description'),
                    # The detailed description may use either the UPnP or ARIB namespace
                    long_description=element.findtext(f'{{{UPNP_NAMESPACE}}}longDescription')
                    or element.findtext(f'{{{ARIB_NAMESPACE}}}longDescription'),
                    channel_name=element.findtext(f'{{{UPNP_NAMESPACE}}}channelName'),
                    genres=tuple(genre.text or '' for genre in element.iterfind(f'{{{UPNP_NAMESPACE}}}genre')),
                    date=element.findtext(f'{{{DC_NAMESPACE}}}date'),
                    duration=resources[0].attributes.get('duration') if len(resources) > 0 else None,
                    resources=resources,
                    protection=_read_protection(element, resources, read_remaining_copy_count(element)),
                    raw_xml=ET.tostring(element, encoding='unicode'),
                )
            )

    return objects


def _parse_resource(element: ET.Element) -> Resource:
    """
    Convert a res element to a resource model.

    Args:
        element (ET.Element): DIDL-Lite res element

    Returns:
        Resource: Resource model
    """

    return Resource(
        url=(element.text or '').strip(),
        protocol_info=parse_protocol_info(element.get('protocolInfo', '')),
        attributes=dict(element.attrib),
        raw_xml=ET.tostring(element, encoding='unicode'),
    )


def _read_protection(
    item: ET.Element,
    resources: tuple[Resource, ...],
    remaining_copy_count: ProtectionValue[int],
) -> RecordingProtection:
    """
    Build protection information from the original resource's DTCP.COM_FLAGS and the profile's copy count.

    Args:
        item (ET.Element): DIDL-Lite item element
        resources (tuple[Resource, ...]): Recording resources
        remaining_copy_count (ProtectionValue[int]): Remaining copy count read by the profile

    Returns:
        RecordingProtection: Protection information available from the listing
    """

    # Determine Move support from the advertised original-format resource used for lossless transfer
    target: Resource | None = None
    for resource in resources:
        if resource.protocol_info.is_dtcp is True and resource.protocol_info.is_converted is not True:
            target = resource
            break

    flags_value = target.protocol_info.parameters.get('DTCP.COM_FLAGS') if target is not None else None
    if flags_value is None:
        # Some devices support Move without advertising it, so omission does not imply lack of support
        is_move_supported = ProtectionValue[bool](status='omitted', source='protocol_info')
        is_transaction_move_supported = ProtectionValue[bool](status='omitted', source='protocol_info')
    else:
        try:
            flags = int(flags_value[:8], 16)
            is_move_supported = ProtectionValue[bool](
                status='known', value=flags & _DTCP_FLAG_MOVE != 0, source='protocol_info'
            )
            is_transaction_move_supported = ProtectionValue[bool](
                status='known',
                value=flags & _DTCP_FLAG_TRANSACTION_MOVE != 0,
                source='protocol_info',
            )
        except ValueError:
            is_move_supported = ProtectionValue[bool](status='unsupported', source='protocol_info')
            is_transaction_move_supported = ProtectionValue[bool](status='unsupported', source='protocol_info')

    return RecordingProtection(
        remaining_copy_count=remaining_copy_count,
        is_move_supported=is_move_supported,
        is_transaction_move_supported=is_transaction_move_supported,
    )
