"""Exercise normal CLI operations against a test source."""

import asyncio
import sys
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from aiohttp import web
from rich.progress import Progress
from rich.prompt import Confirm, IntPrompt
from typer.testing import CliRunner

from pydtcpip.__main__ import ProgressReporter, app
from pydtcpip.dlna.didl import DC_NAMESPACE, DIDL_NAMESPACE, parse_didl
from pydtcpip.dlna.profiles import GENERIC
from pydtcpip.events import MoveCompleted, TransferProgressed, TransferReceived, TransferStarted
from pydtcpip.models import Recording
from tests.fakes import FakeAuthority, FakeDevice, FakeMediaServer, FakeSourceAKE


@pytest.mark.anyio
async def test_nasne_final_move_warning_before_confirmation(
    sink_device: FakeDevice, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read nasne metadata over HTTP and warn before the user declines the final Move."""

    monkeypatch.setenv('PYDTCPIP_CERTIFICATE', sink_device.certificate.hex())
    monkeypatch.setenv('PYDTCPIP_PRIVATE_KEY', sink_device.private_key.hex())
    description = """<root xmlns="urn:schemas-upnp-org:device-1-0"><device><modelName>buffalo-nasne</modelName>
    <serviceList><service><serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>
    <controlURL>/control</controlURL></service></serviceList></device></root>"""
    didl = """<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
    xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:av="urn:schemas-sony-com:av">
    <item id="recording" parentID="0"><dc:title>Final recording</dc:title><av:COGCount>1</av:COGCount>
    <res protocolInfo="http-get:*:application/x-dtcp1:DLNA.ORG_CI=0">http://127.0.0.1/unused</res>
    </item></DIDL-Lite>"""

    async def describe(request: web.Request) -> web.Response:
        return web.Response(text=description, content_type='text/xml')

    async def browse(request: web.Request) -> web.Response:
        return web.Response(
            text='<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            '<u:BrowseResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">'
            f'<Result>{escape(didl)}</Result><NumberReturned>1</NumberReturned><TotalMatches>1</TotalMatches>'
            '</u:BrowseResponse></s:Body></s:Envelope>',
            content_type='text/xml',
        )

    http_app = web.Application()
    http_app.router.add_get('/description.xml', describe)
    http_app.router.add_post('/control', browse)
    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = runner.addresses[0][1]
    output = tmp_path / 'recording.m2ts'

    def invoke() -> str:
        cli = CliRunner()
        with cli.isolation(input='n\n') as streams:
            monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
            with pytest.raises(SystemExit) as error:
                app(
                    [
                        '--data-dir',
                        str(tmp_path),
                        'move',
                        str(output),
                        '--server',
                        f'http://127.0.0.1:{port}/description.xml',
                        '--id',
                        'recording',
                    ]
                )
            assert error.value.code == 1
            return streams[1].getvalue().decode()

    try:
        text = await asyncio.to_thread(invoke)
    finally:
        await runner.cleanup()
    assert 'Only the final Move remains.' in text
    assert 'Moving will delete the source recording.' in text
    assert text.index('Only the final Move remains.') < text.index('Move this recording and consume')
    assert output.exists() is False


def test_progress_routes_interleaved_transfer_events() -> None:
    """Concurrent event streams must update and remove only their own bars."""

    progress = Progress(auto_refresh=False, disable=True)
    reporter = ProgressReporter(progress, 'Receiving')
    reporter(TransferStarted(transfer_id='first', total_http_bytes=None, total_content_bytes=100))
    reporter(TransferStarted(transfer_id='second', total_http_bytes=None, total_content_bytes=None))
    reporter(TransferProgressed(transfer_id='first', http_bytes=64, content_bytes=50, written_bytes=50))
    reporter(TransferProgressed(transfer_id='second', http_bytes=128, content_bytes=100, written_bytes=100))
    assert [task.completed for task in progress.tasks] == [50, 128]
    reporter(TransferReceived(transfer_id='first', http_bytes=128, content_bytes=100))
    reporter(MoveCompleted(transfer_id='first'))
    assert len(progress.tasks) == 1
    assert progress.tasks[0].completed == 128
    assert progress.tasks[0].finished is False
    reporter(TransferReceived(transfer_id='second', http_bytes=256, content_bytes=200))
    reporter(MoveCompleted(transfer_id='second'))
    assert progress.tasks == []


def test_arib_metadata_and_saved_xml_use_standard_unicode(tmp_path: Path) -> None:
    """Legacy ARIB marks in incoming titles must be readable in filenames and sidecar XML."""

    raw_xml = f'''<DIDL-Lite xmlns="{DIDL_NAMESPACE}" xmlns:dc="{DC_NAMESPACE}"
        xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
      <item id="recording-id\ue0fe" parentID="0">
        <dc:title>テスト番組\ue0fe\ue192</dc:title>
        <dc:description>\ue193新番組・\ue084さん・🈑・未定義\uec00</dc:description>
        <upnp:longDescription>説明\ue0fe</upnp:longDescription>
        <upnp:channelName>チャンネル\ue192</upnp:channelName>
        <upnp:genre>ジャンル\ue193</upnp:genre>
        <upnp:extension>\ue0fe</upnp:extension>
        <res protocolInfo="http-get:*:application/x-dtcp1:DTCP.COM_FLAGS=80000000">http://127.0.0.1/recording/\ue0fe</res>
      </item>
    </DIDL-Lite>'''
    recording = parse_didl(raw_xml, GENERIC)[0]
    assert isinstance(recording, Recording)
    assert recording.title == 'テスト番組🈑🈞'
    assert recording.description == '🈟新番組・𠮷さん・🈑・未定義\uec00'
    assert recording.long_description == '説明🈑'
    assert recording.channel_name == 'チャンネル🈞'
    assert recording.genres == ('ジャンル🈟',)
    metadata = tmp_path / f'{recording.title}.xml'
    metadata.write_text(recording.raw_xml, encoding='utf-8')
    saved = metadata.read_text(encoding='utf-8')
    assert 'テスト番組🈑🈞' in saved
    saved_item = ET.fromstring(saved)
    assert saved_item.findtext(f'{{{DC_NAMESPACE}}}title') == 'テスト番組🈑🈞'
    assert saved_item.findtext('{urn:schemas-upnp-org:metadata-1-0/upnp/}extension') == '\ue0fe'
    assert '\ue192' not in saved
    assert '\uec00' in saved
    assert recording.id == 'recording-id\ue0fe'
    assert recording.resources[0].url == 'http://127.0.0.1/recording/\ue0fe'
    assert recording.resources[0].protocol_info.parameters['DTCP.COM_FLAGS'] == '80000000'


@pytest.mark.anyio
@pytest.mark.parametrize('command', ['stream', 'move'])
@pytest.mark.parametrize('credential_source', ['default', 'data-dir', 'file', 'environment'])
async def test_noninteractive_transfer(
    authority: FakeAuthority,
    sink_device: FakeDevice,
    source_device: FakeDevice,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    credential_source: str,
) -> None:
    """A URL and --yes avoid prompts even on a terminal, with credentials from each supported source."""

    monkeypatch.delenv('PYDTCPIP_CERTIFICATE', raising=False)
    monkeypatch.delenv('PYDTCPIP_PRIVATE_KEY', raising=False)
    # Point default paths on all OSes to temporary storage rather than the user's data directory
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    if sys.platform == 'darwin':
        default_dir = tmp_path / 'Library' / 'Application Support' / 'pydtcpip'
    elif sys.platform == 'win32':
        default_dir = tmp_path / 'appdata' / 'pydtcpip'
    else:
        default_dir = tmp_path / 'data' / 'pydtcpip'
    data_dir = tmp_path / 'custom-device' if credential_source == 'data-dir' else default_dir
    data_dir.mkdir(parents=True)
    credentials_file = tmp_path / 'other.env' if credential_source == 'file' else data_dir / 'credentials.env'
    if credential_source == 'environment':
        monkeypatch.setenv('PYDTCPIP_CERTIFICATE', sink_device.certificate.hex())
        monkeypatch.setenv('PYDTCPIP_PRIVATE_KEY', sink_device.private_key.hex())
    else:
        credentials_file.write_text(
            f'PYDTCPIP_CERTIFICATE={sink_device.certificate.hex()}\n'
            f'PYDTCPIP_PRIVATE_KEY={sink_device.private_key.hex()}\n',
            encoding='utf-8',
        )

    def reject_prompt(*args: object, **kwargs: object) -> None:
        raise AssertionError('A prompt appeared despite the required arguments being supplied.')

    monkeypatch.setattr(IntPrompt, 'ask', reject_prompt)
    monkeypatch.setattr(Confirm, 'ask', reject_prompt)
    content = b'CLI recording content' * 1000
    output = tmp_path / 'recording.m2ts'
    srm_data = authority.issue_srm(2)
    async with (
        FakeSourceAKE(authority, source_device, srm=srm_data) as source,
        FakeMediaServer(source, content) as server,
    ):
        args = ['--data-dir', str(data_dir)] if credential_source == 'data-dir' else []
        if command == 'stream':
            args.extend(['stream', server.url])
        else:
            args.extend(['move', str(output), '--url', server.url, '--yes'])
        if credential_source == 'file':
            args.extend(['--credentials', str(credentials_file)])

        def invoke() -> bytes:
            runner = CliRunner()
            # Treat test stdin as a terminal to verify --yes
            with runner.isolation() as streams:
                monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
                app(args, standalone_mode=False)
                sys.stdout.flush()
                return streams[0].getvalue()

        stdout = await asyncio.to_thread(invoke)

    if command == 'stream':
        assert stdout == content
    else:
        assert output.read_bytes() == content
        assert source.log[-2:] == ['finalize', 'complete']
        assert (tmp_path / 'recording.m2ts.pydtcpip-resume.json').exists() is False
    assert (data_dir / 'srm.bin').read_bytes() == srm_data
    assert source.errors == []
