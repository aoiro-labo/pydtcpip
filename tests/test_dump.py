"""Verify that redacted dumps do not retain identifiers or program content."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest

from pydtcpip.dump import Redactor


_FIXTURE_DIRECTORY = Path(__file__).parent / 'fixtures'

_DESCRIPTION = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
<UDN>uuid:12345678-90ab-cdef-1234-a1b2c3d4e5f6</UDN>
<friendlyName>リビングのレコーダー</friendlyName>
<serialNumber>SN-0012345</serialNumber>
<UPC>012345678905</UPC>
<manufacturer>Example</manufacturer>
<modelName>Example Recorder</modelName>
<dlna:X_DLNACAP xmlns:dlna="urn:schemas-dlna-org:device-1-0">av-upload,dtcp-move</dlna:X_DLNACAP>
<x:Socket xmlns:x="urn:example">198.51.100.20:58293</x:Socket>
<x:Mac xmlns:x="urn:example" owner="家族">a1:b2:c3:d4:e5:f6</x:Mac>
<presentationURL>http://[fe80::a1b2:c3ff:fed4:e5f6]:8080/</presentationURL>
</device></root>
"""

_DIDL = """<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:v="urn:example:vendor">
<item id="20201231235959/REC_202012312359_001122334455" parentID="0">
<dc:title><![CDATA[秘密の番組]]></dc:title>
<dc:date>2020-12-31T23:59:59</dc:date>
<upnp:channelName>テスト放送</upnp:channelName>
<upnp:class>object.item.videoItem</upnp:class>
<v:copycount>9</v:copycount>
<v:network_id>7fe1</v:network_id>
<v:service_id>408</v:service_id>
<v:info title="属性に入った番組名" start="2020-12-31T23:59:59"/>
<v:prog>子要素の前の番組名<v:x/></v:prog>
<!-- コメントに入った番組名 -->
<res protocolInfo="http-get:*:application/x-dtcp1;DTCP1HOST=198.51.100.20;DTCP1PORT=5000:DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01110000000000000000000000000000" size="1966473216" duration="01:00:08.000">http://198.51.100.20:8080/秘密の番組_a1b2c3d4e5f6.dtv</res>
</item>
</DIDL-Lite>
"""


def test_description_keeps_only_known_values() -> None:
    redactor = Redactor()
    redacted = redactor.redact_xml(_DESCRIPTION, 'description')

    # User-assigned names, serial numbers, UPCs, vendor values, UUIDs, and addresses must not remain
    for secret in (
        '12345678-90ab-cdef-1234-a1b2c3d4e5f6',
        'リビングのレコーダー',
        'SN-0012345',
        '012345678905',
        '家族',
        '198.51.100.20',
        'a1:b2:c3:d4:e5:f6',
        'fe80::a1b2:c3ff:fed4:e5f6',
    ):
        assert secret not in redacted

    # Device identification values and namespace declaration positions remain intact
    assert '<manufacturer>Example</manufacturer>' in redacted
    assert '<modelName>Example Recorder</modelName>' in redacted
    assert '<x:Socket xmlns:x="urn:example">' in redacted
    assert (
        '<dlna:X_DLNACAP xmlns:dlna="urn:schemas-dlna-org:device-1-0">av-upload,dtcp-move</dlna:X_DLNACAP>' in redacted
    )

    # The same address receives the same replacement across documents
    assert 'DTCP1HOST=192.0.2.1' in redactor.redact_xml(_DIDL, 'didl')


def test_didl_redacts_every_unknown_place() -> None:
    # Redact unknown values in CDATA, attributes, mixed text, comments, URL paths, and numeric MAC addresses
    redacted = Redactor().redact_xml(_DIDL, 'didl')
    for secret in (
        '秘密の番組',
        '2020-12-31T23:59:59',
        'テスト放送',
        '属性に入った番組名',
        '子要素の前の番組名',
        'コメントに入った番組名',
        '20201231235959',
        '202012312359',
        '001122334455',
        'a1b2c3d4e5f6',
        '198.51.100.20',
    ):
        assert secret not in redacted

    # Values needed for device compatibility remain
    assert '<v:copycount>9</v:copycount>' in redacted
    assert '<v:network_id>7fe1</v:network_id>' in redacted
    assert '<v:service_id>408</v:service_id>' in redacted
    assert '<upnp:class>object.item.videoItem</upnp:class>' in redacted
    assert 'size="1966473216" duration="01:00:08.000"' in redacted
    assert 'DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01110000000000000000000000000000' in redacted


def test_item_fragment_without_root_is_redacted() -> None:
    # Apply the same rules to an item fragment without a root element
    fragment = (
        '<ns0:item xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:ns0="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" id="1">'
        '<dc:title>秘密の番組</dc:title><dc:date>2020-12-31T23:59:59</dc:date></ns0:item>'
    )
    redacted = Redactor().redact_xml(fragment, 'didl')
    assert '秘密の番組' not in redacted
    assert '2020-12-31T23:59:59' not in redacted


def test_recording_identifiers_and_url_references_share_replacements() -> None:
    """Replace numeric recording IDs in metadata and resource URLs consistently across files."""

    redactor = Redactor()
    xml = """<DIDL-Lite><container id="12345" parentID="0"/>
    <item id="1234567890123456789" parentID="12345" refID="1234567890123456789">
    <res size="1234567890123456789" protocolInfo="http-get:*:video/mp4:DLNA.ORG_FLAGS=01110000000000000000000000000000"
    importUri="http://192.0.2.10/import?id=1234567890123456789">http://192.0.2.10/media/1234567890123456789?id=1234567890123456789&amp;token=private-token</res>
    </item></DIDL-Lite>"""
    root = ET.fromstring(redactor.redact_xml(xml, 'didl'))
    folder, item = root
    resource = item[0]
    assert folder.get('id') != '12345'
    assert folder.get('parentID') == '0'
    assert item.get('parentID') == folder.get('id')
    assert item.get('id') != '1234567890123456789'
    assert item.get('refID') == item.get('id')
    url = urlsplit(resource.text or '')
    assert url.path.split('/')[-1] == item.get('id')
    assert parse_qs(url.query)['id'] == [item.get('id')]
    assert 'private-token' not in url.query
    assert parse_qs(urlsplit(resource.attrib['importUri']).query)['id'] == [item.get('id')]
    assert resource.get('size') == '1234567890123456789'
    assert 'DLNA.ORG_FLAGS=01110000000000000000000000000000' in resource.attrib['protocolInfo']
    again = ET.fromstring(redactor.redact_xml('<item id="1234567890123456789"/>', 'didl'))
    assert again.get('id') == item.get('id')


def test_headers_keep_only_known_values() -> None:
    # Redact filenames and retrieval dates while retaining headers describing the stream format
    redacted = dict(
        Redactor().redact_headers(
            [
                ('Content-Type', 'application/x-dtcp1;DTCP1HOST=198.51.100.20;DTCP1PORT=5000'),
                ('Content-Disposition', 'attachment; filename="秘密の番組.ts"'),
                ('Date', 'Thu, 31 Dec 2020 23:59:59 GMT'),
                ('contentFeatures.dlna.org', 'DLNA.ORG_CI=0'),
            ]
        )
    )
    assert redacted['Content-Type'] == 'application/x-dtcp1;DTCP1HOST=192.0.2.1;DTCP1PORT=5000'
    assert '秘密の番組' not in redacted['Content-Disposition']
    assert '2020' not in redacted['Date']
    assert redacted['contentFeatures.dlna.org'] == 'DLNA.ORG_CI=0'


@pytest.mark.parametrize('kind', ['didl', 'description'])
def test_short_unknown_integers_survive_without_retaining_sensitive_fields(kind: str) -> None:
    """Retain small counters in text, CDATA, and attributes, while masking identifiers and personal data."""

    xml = """<root xmlns:shp="urn:schemas-sharp-co-jp:av">
    <shp:ccnum>10</shp:ccnum><state>0</state><limit><![CDATA[999]]></limit>
    <vendor flag="1" count="123" pin="123" owner="123" deviceID="12" date="123"/>
    <padded>01</padded><large>1000</large><negative>-1</negative><decimal>1.2</decimal>
    <serialNumber>123</serialNumber><title>123</title><friendlyName>123</friendlyName>
    <password>123</password><recordingId>123</recordingId><timestamp>123</timestamp>
    <owner><value>123</value><part value="123"/></owner><!-- 123 -->
    </root>"""
    # Both supported document kinds use the same rule for unknown vendor metadata
    redacted = Redactor().redact_xml(xml, 'didl' if kind == 'didl' else 'description')
    root = ET.fromstring(redacted)
    assert root.findtext('{urn:schemas-sharp-co-jp:av}ccnum') == '10'
    assert root.findtext('state') == '0'
    assert root.findtext('limit') == '999'
    vendor = root.find('vendor')
    assert vendor is not None
    assert vendor.get('flag') == '1'
    assert vendor.get('count') == '123'
    for field in ('pin', 'owner', 'deviceID', 'date'):
        assert vendor.get(field) == 'redacted'
    for field in (
        'padded',
        'large',
        'negative',
        'decimal',
        'serialNumber',
        'title',
        'friendlyName',
        'password',
        'recordingId',
        'timestamp',
        'owner/value',
    ):
        assert root.findtext(field) == 'redacted'
    part = root.find('owner/part')
    assert part is not None
    assert part.get('value') == 'redacted'
    assert '<!-- 123 -->' not in redacted


def test_fixtures_contain_no_private_network_addresses_or_identifiers() -> None:
    # Detect local network addresses or device UUIDs left in contributed fixtures
    private_address = re.compile(r'(?<![\d.])(?:10\.\d+|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d+\.\d+')
    device_uuid = re.compile(r'uuid:(?!00000000-0000-0000-0000-)[0-9a-fA-F-]{36}')
    for path in sorted(_FIXTURE_DIRECTORY.rglob('*.xml')):
        text = path.read_text(encoding='utf-8')
        assert private_address.search(text) is None, f'{path} contains a private network address'
        assert device_uuid.search(text) is None, f'{path} contains a device UUID'
