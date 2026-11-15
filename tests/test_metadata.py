"""Exercise recorder metadata parsing and copy-count conventions."""

import pytest

from pydtcpip import Recording
from pydtcpip.dlna.didl import parse_didl
from pydtcpip.dlna.profiles import PROFILES


def recording_xml(fields: str = '', attributes: str = '', resource_url: str = 'http://192.0.2.1/media') -> str:
    return f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
      xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"
      xmlns:arib="urn:schemas-arib-or-jp:elements-1-0/" xmlns:av="urn:schemas-sony-com:av"
      xmlns:pxn="urn:schemas-panasonic-com:pxn" xmlns:shp="urn:schemas-sharp-co-jp:shp"
      xmlns:regza="urn:schemas-toshiba-co-jp:regzadata-1-0/">
      <item id="V_42" refID="42" parentID="0"><dc:title>Sample\ue0fe</dc:title>
      <upnp:class>object.item.videoItem</upnp:class><upnp:channelName>Example channel</upnp:channelName>
      <upnp:channelNr>101</upnp:channelNr><upnp:scheduledStartTime>2026-01-01T20:00:00+09:00</upnp:scheduledStartTime>
      <upnp:scheduledEndTime>2026-01-01T20:30:00+09:00</upnp:scheduledEndTime>
      <arib:longDescription>First paragraph</arib:longDescription><upnp:longDescription>Cast</upnp:longDescription>
      <arib:videoComponentType>179</arib:videoComponentType><arib:audioComponentType main="1">3</arib:audioComponentType>
      <arib:serviceID>100</arib:serviceID><upnp:rating type="age">12</upnp:rating>
      {fields}<res {attributes} duration="0:30:00.000" resolution="1920x1080" size="123456"
      protocolInfo="http-get:*:application/x-dtcp1:DLNA.ORG_CI=0;DTCP.COM_FLAGS=C0000000">{resource_url}</res>
      </item></DIDL-Lite>"""


@pytest.mark.parametrize(
    ('profile_name', 'fields', 'attributes', 'expected'),
    [
        ('sony_bdz', '<av:COGCount>10</av:COGCount>', '', 9),
        ('sharp', '<shp:ccnum>0x01</shp:ccnum>', '', 0),
        ('toshiba', '<regza:copycount>0x0a</regza:copycount>', '', 9),
        ('panasonic', '', 'pxn:CopyCount="9"', 8),
        ('panasonic', '', 'pxn:CopyCount="1"', 0),
        ('stb', '', 'allowedUse="0:0:10"', 9),
        ('stb_hikaritv', '', 'allowedUse="0:0:1"', 0),
        ('stb_stw2000', '', 'allowedUse="0:0:9"', 8),
        ('recon', '', 'allowedUse="0:0:1"', 0),
        ('recbox', '', 'pxn:CopyCount="10"', 9),
        ('linkstation', '', 'pxn:CopyCount="10"', 9),
    ],
)
def test_finite_counts_include_the_final_move(profile_name: str, fields: str, attributes: str, expected: int) -> None:
    profile = next(profile for profile in PROFILES if profile.name == profile_name)
    recording = parse_didl(recording_xml(fields, attributes), profile)[0]
    assert isinstance(recording, Recording)
    assert recording.protection.remaining_copy_count.value == expected
    assert recording.protection.remaining_copy_count.status == 'known'
    assert recording.protection.reported_copy_counts[0].includes_final_move is True
    assert recording.protection.remaining_copy_count.observed_at is not None


@pytest.mark.parametrize(
    ('attributes', 'status', 'unlimited'),
    [
        ('', 'omitted', False),
        ('pxn:CopyCount="CF"', 'unsupported', True),
        ('pxn:CopyCount="-1"', 'unsupported', True),
        ('pxn:CopyCount="0"', 'unsupported', False),
        ('pxn:CopyCount="redacted"', 'unsupported', False),
    ],
)
def test_omitted_unlimited_and_invalid_counts_remain_distinct(attributes: str, status: str, unlimited: bool) -> None:
    profile = next(profile for profile in PROFILES if profile.name == 'panasonic')
    recording = parse_didl(recording_xml(attributes=attributes), profile)[0]
    assert isinstance(recording, Recording)
    assert recording.protection.remaining_copy_count.value is None
    assert recording.protection.remaining_copy_count.status == status
    if attributes:
        assert recording.protection.reported_copy_counts[0].is_unlimited is unlimited
    else:
        assert recording.protection.reported_copy_counts == ()


def test_original_resource_controls_count_and_move_capabilities() -> None:
    profile = next(profile for profile in PROFILES if profile.name == 'panasonic')
    other_resources = """<res pxn:CopyCount="2" protocolInfo="http-get:*:application/x-dtcp1:DTCP.COM_FLAGS=00000000">http://192.0.2.1/unknown</res>
    <res pxn:CopyCount="3" protocolInfo="http-get:*:application/x-dtcp1:DLNA.ORG_CI=1;DTCP.COM_FLAGS=00000000">http://192.0.2.1/converted</res>"""
    recording = parse_didl(recording_xml(other_resources, 'pxn:CopyCount="10"'), profile)[0]
    assert isinstance(recording, Recording)
    assert recording.original_resource is not None
    assert recording.original_resource.url == 'http://192.0.2.1/media'
    assert recording.protection.remaining_copy_count.value == 9
    assert recording.protection.is_move_supported.value is True
    assert [count.value for count in recording.protection.reported_copy_counts] == [2, 3, 10]
