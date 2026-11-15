"""Exercise family metadata through real local HTTP and SOAP exchanges."""

import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from html import escape
from xml.etree import ElementTree as ET

import aiohttp
import pytest
from aiohttp import web
from aiohttp.abc import AbstractResolver, ResolveResult

from pydtcpip import DLNAClient, Recording
from pydtcpip.dlna.didl import parse_didl
from pydtcpip.dlna.extensions.xml_chapters import ChapterFormat, parse_chapters
from pydtcpip.dlna.profiles import PROFILES
from pydtcpip.errors import DLNAError


_CDS = 'urn:schemas-upnp-org:service:ContentDirectory:1'
_PVR = 'urn:schemas-s-bras-org:service:X_PvrControl:1'


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


_CHAPTER_CASES: list[tuple[ChapterFormat, str]] = [
    (
        'sony',
        '<root xmlns:s="urn:schemas-sony-com:av"><s:content_chapter_info><s:chapter><s:chapter_point>12.345</s:chapter_point></s:chapter></s:content_chapter_info></root>',
    ),
    ('panasonic', '<root><chapterList><item><timeCode>00:00:12.345</timeCode></item></chapterList></root>'),
    ('sharp', '<root><chapter>00:00:12.345</chapter></root>'),
    ('toshiba', '<root xmlns="urn:example:chapters"><Chapter>00:00:12.345</Chapter></root>'),
    (
        'shared_tags',
        '<root xmlns="urn:example:tags"><item><tagList><tag><posTime>00:00:12.345</posTime></tag></tagList></item></root>',
    ),
]


@pytest.mark.parametrize(('format', 'document'), _CHAPTER_CASES)
def test_chapter_formats_preserve_only_device_points(format: ChapterFormat, document: str) -> None:
    assert [chapter.position_ms for chapter in parse_chapters(document, format)] == [12345]


@pytest.mark.parametrize(
    'document',
    [
        '<root/>',
        '<root><chapterList><item/></chapterList></root>',
        '<root><chapterList><item><timeCode>invalid</timeCode></item></chapterList></root>',
    ],
)
def test_invalid_chapter_documents_are_not_empty_successes(document: str) -> None:
    with pytest.raises(DLNAError):
        parse_chapters(document, 'panasonic')
    assert parse_chapters('<root><chapterList/></root>', 'panasonic') == ()


class LocalResolver(AbstractResolver):
    """Route documented fixed metadata ports to one private in-process test server."""

    def __init__(self, port: int) -> None:
        self.port = port

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[ResolveResult]:
        return [ResolveResult(hostname=host, host='127.0.0.1', port=self.port, family=socket.AF_INET, proto=0, flags=0)]

    async def close(self) -> None:
        pass


class MetadataSource:
    """A synthetic device serving independent metadata documents over HTTP and SOAP."""

    def __init__(self, manufacturer: str, model: str, didl: str, chapter: str = '', action: str = '') -> None:
        self.manufacturer = manufacturer
        self.model = model
        self.didl = didl
        self.chapter = chapter
        self.action = action
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.requests: list[str] = []
        self.raw_description = ''
        self.requery_didl: str | None = None

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(request.path)
        if request.path == '/description.xml':
            self.raw_description = f"""<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
            <manufacturer>{self.manufacturer}</manufacturer><modelName>{self.model}</modelName>
            <friendlyName>Test recorder</friendlyName><serviceList><service><serviceType>{_CDS}</serviceType>
            <controlURL>/control</controlURL><SCPDURL>/scpd.xml</SCPDURL></service>
            <service><serviceType>{_PVR}</serviceType><controlURL>/pvr</controlURL><SCPDURL>/pvr.xml</SCPDURL>
            </service></serviceList></device></root>"""
            return web.Response(text=self.raw_description, content_type='text/xml')
        if request.path.endswith('.xml'):
            actions = (
                [self.action]
                if request.path == '/scpd.xml'
                else ['X_GetTitleList2', 'X_GetTitleInfo', 'X_GetMediaInfo']
            )
            entries = ''.join(f'<action><name>{name}</name></action>' for name in actions if name)
            return web.Response(
                text=f'<scpd xmlns="urn:schemas-upnp-org:service-1-0"><actionList>{entries}</actionList></scpd>'
            )
        if request.path == '/chapters':
            return web.Response(text=self.chapter)
        if request.path == '/recorded/thumbnailMapGet':
            assert request.query == {'id': '42'}
            return web.Response(body=bytes.fromhex('00000003 00000064 000000c8 0000012c'))
        if request.path == '/recorded/recordedContentChpDataGet':
            assert request.query == {'id': '42', 'offset': '0', 'length': '0'}
            # Stream positions 150 and 350; only the first lies between thumbnail map entries
            return web.Response(
                body=bytes.fromhex('00b0040000000000 0000000000000000 00f00a0000000000 0000000000000000')
            )
        if request.path == '/recorded/titleListGet':
            assert request.query['withDescriptionLong'] == '1'
            assert request.query['withUserData'] == '0'
            return web.json_response(
                {
                    'errorcode': 0,
                    'totalMatches': 1,
                    'numberReturned': 1,
                    'item': [{'id': 42, 'descriptionLong': 'Extended information', 'startDateTime': 1767265200}],
                }
            )
        envelope = ET.fromstring(await request.read())
        body = envelope.find('{http://schemas.xmlsoap.org/soap/envelope/}Body')
        assert body is not None
        action = body[0]
        name = action.tag.rpartition('}')[2]
        arguments = {child.tag: child.text or '' for child in action}
        self.calls.append((name, arguments))
        if name == 'Browse':
            result = self.didl
            if self.requery_didl is not None:
                self.didl = self.requery_didl
        elif name == self.action:
            result = self.chapter
        elif name == 'X_GetTitleList2':
            result = '<root><item id="00000000000000002a"><recordDestinationID>HDD</recordDestinationID><description>Extra details</description></item></root>'
        elif name == 'X_GetTitleInfo':
            assert arguments == {'TitleID': '00000000000000002a'}
            result = '<root><recordStartDate>2026-01-01T19:59:57</recordStartDate><startPTS>270000</startPTS></root>'
        elif name == 'X_GetMediaInfo':
            assert arguments == {'recordDestinationID': 'HDD'}
            result = '<root><freeCapacity>123456789</freeCapacity></root>'
        else:
            raise AssertionError(f'Unexpected SOAP action: {name}')
        namespace = action.tag[1:].partition('}')[0]
        return web.Response(
            text=f'''<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
        <u:{name}Response xmlns:u="{namespace}"><Result>{escape(result)}</Result><NumberReturned>1</NumberReturned>
        <TotalMatches>1</TotalMatches></u:{name}Response></s:Body></s:Envelope>''',
            content_type='text/xml',
        )

    @asynccontextmanager
    async def serve(self) -> AsyncGenerator[tuple[str, int]]:
        app = web.Application()
        app.router.add_route('*', '/{path:.*}', self.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = runner.addresses[0][1]
        try:
            yield f'http://127.0.0.1:{port}/description.xml', port
        finally:
            await runner.cleanup()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('manufacturer', 'model', 'fields', 'attributes', 'format', 'action'),
    [
        ('Sony', 'BDZ-TEST', '<av:chapterInfo>/chapters</av:chapterInfo><av:COGCount>10</av:COGCount>', '', 'sony', ''),
        ('Panasonic', 'BD/DVD Recorder', '', 'pxn:ChapterList="/chapters" pxn:CopyCount="10"', 'panasonic', ''),
        ('Sharp Corporation', 'BD-TEST', '<shp:chapterList>/chapters</shp:chapterList>', '', 'sharp', ''),
        ('TOSHIBA', 'DBR-TEST', '', '', 'toshiba', 'X_Toshiba_GetChapterList'),
        ('I-O DATA', 'GV-NTX2', '', '', 'shared_tags', 'X_TShrGetTags'),
    ],
)
async def test_metadata_collection(
    manufacturer: str,
    model: str,
    fields: str,
    attributes: str,
    format: ChapterFormat,
    action: str,
) -> None:
    chapter = dict(_CHAPTER_CASES)[format]
    # Sony detail IDs match the original numeric suffix, while chapter SOAP must retain the original DIDL ID
    didl = recording_xml(fields, attributes).replace(' refID="42"', '')
    source = MetadataSource(manufacturer, model, didl, chapter, action)
    async with source.serve() as (location, _), DLNAClient() as dlna:
        server = await dlna.get_server(location)
        recording = await server.get_metadata('V_42')
        assert isinstance(recording, Recording)
        assert source.requests == ['/description.xml', '/control']
        metadata = await server.collect_metadata(recording)
    assert metadata.chapters.chapters[0].position_ms == 12345
    assert metadata.chapters.raw_responses
    assert recording.long_description == 'First paragraph\nCast'
    assert recording.audio_components[0].attributes == {'main': '1'}
    assert recording.channel_number == '101'
    assert recording.source_xml is not None and '\ue0fe' in recording.source_xml
    assert '\ue0fe' not in recording.raw_xml
    assert metadata.device_description_xml == source.raw_description
    if action:
        expected = {'ObjectID': 'V_42'}
        if action == 'X_TShrGetTags':
            expected.update({'TagIDs': '', 'Filter': '', 'Type': ''})
        assert (action, expected) in source.calls
    if model == 'BDZ-TEST':
        assert [(query.name, query.status) for query in metadata.queries] == [
            ('chapters', 'known'),
            ('recording_details', 'known'),
            ('recording_start', 'known'),
            ('storage', 'known'),
        ]
        assert '270000' in metadata.model_dump_json()


@pytest.mark.anyio
async def test_nasne_http_metadata_keeps_unmappable_chapters() -> None:
    source = MetadataSource('Buffalo', 'buffalo-nasne', recording_xml('<av:COGCount>9</av:COGCount>'))
    async with source.serve() as (_, port):
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=LocalResolver(port))) as session:
            async with DLNAClient(http_session=session) as dlna:
                server = await dlna.get_server('http://nasne.test/description.xml')
                recording = await server.get_metadata('V_42')
                assert isinstance(recording, Recording)
                metadata = await server.collect_metadata(recording)
    assert [chapter.position_ms for chapter in metadata.chapters.chapters] == [7500, None]
    assert [chapter.source_position for chapter in metadata.chapters.chapters] == [150, 350]
    assert [chapter.is_estimated for chapter in metadata.chapters.chapters] == [True, False]
    assert metadata.queries[-1].data['recording'] == {
        'id': 42,
        'descriptionLong': 'Extended information',
        'startDateTime': 1767265200,
    }
    assert len(metadata.chapters.raw_responses) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('manufacturer', 'model', 'root'),
    [
        ('HUAWEI', 'TT01', '0/video/rec/all'),
        ('Mitsubishi Electric Corporation', 'AM900', '0-0-0-0'),
        ('Panasonic', 'STW2000', '0/rec/all'),
        ('Example', 'Standard media server', '0'),
    ],
)
async def test_recording_enumeration_uses_the_family_container(manufacturer: str, model: str, root: str) -> None:
    source = MetadataSource(manufacturer, model, recording_xml())
    async with source.serve() as (location, _), DLNAClient() as dlna:
        server = await dlna.get_server(location)
        recordings = [recording async for recording in server.iter_recordings()]
        assert len(recordings) == 1
        assert source.calls[0][1]['ObjectID'] == root
        source.calls.clear()
        recordings = [recording async for recording in server.iter_recordings('explicit-folder')]
        assert len(recordings) == 1
        assert source.calls[0][1]['ObjectID'] == 'explicit-folder'
