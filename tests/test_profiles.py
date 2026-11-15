"""Verify that device profile changes stay within their own families."""

import ast
from pathlib import Path

import pytest

from pydtcpip.dlna.description import parse_device_description
from pydtcpip.dlna.didl import parse_didl
from pydtcpip.dlna.profiles import GENERIC, PROFILES, select_profile
from pydtcpip.dlna.profiles.panasonic import PANASONIC
from pydtcpip.dlna.profiles.sie_nasne import SIE_NASNE
from pydtcpip.errors import ClientNotAllowedError
from pydtcpip.models import Recording


_PACKAGE_DIRECTORY = Path(__file__).parent.parent / 'pydtcpip'
_PROFILE_DIRECTORY = _PACKAGE_DIRECTORY / 'dlna' / 'profiles'
_FIXTURE_DIRECTORY = Path(__file__).parent / 'fixtures'

# Modules profiles may import (public types and parent profiles)
_PROFILE_ALLOWED_IMPORTS = frozenset(
    (
        'pydtcpip.dlna.description',
        'pydtcpip.errors',
        'pydtcpip.models',
    )
)

# Expected profile, copy count status, copy count value, and DLNA.ORG_CI of the original resource
## None means the family does not mark the stored format, so the original resource is the one not marked as converted
_EXPECTED = {
    # A regza:copycount of 10 includes the final Move, leaving 9 copies as shown on the TV
    ('toshiba', 'dbr-z620'): ('toshiba', 'known', 9, '0'),
    ('toshiba_regza_tv', '43z570l'): ('toshiba_regza_tv', 'omitted', None, '0'),
    # A pxn:CopyCount of 10 likewise includes the final Move
    ('panasonic', 'dmr-brx2060'): ('panasonic', 'known', 9, None),
}


def _fixture_devices() -> list[tuple[str, str]]:
    """
    Find device fixtures containing a description.

    Returns:
        list[tuple[str, str]]: Family and model directory names
    """

    devices: list[tuple[str, str]] = []
    for description in sorted(_FIXTURE_DIRECTORY.glob('*/*/description.xml')):
        devices.append((description.parent.parent.name, description.parent.name))
    return devices


def _imported_modules(path: Path) -> list[str]:
    """
    Collect modules imported by a Python file.

    Args:
        path (Path): Python source file

    Returns:
        list[str]: Imported module names
    """

    tree = ast.parse(path.read_text(encoding='utf-8'))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
    return modules


def test_profiles_import_only_public_types_and_parent_profiles() -> None:
    # Profiles importing core internals could affect other devices
    for path in sorted(_PROFILE_DIRECTORY.glob('*.py')):
        if path.name == '__init__.py':
            continue
        for module in _imported_modules(path):
            if module.startswith('pydtcpip.') is False:
                continue
            is_allowed = module in _PROFILE_ALLOWED_IMPORTS or module.startswith('pydtcpip.dlna.profiles.')
            assert is_allowed is True, f'{path.name} imports {module}'


def test_core_imports_profiles_only_through_registry() -> None:
    # Direct imports allow family-specific branches to creep into the core
    for path in sorted(_PACKAGE_DIRECTORY.rglob('*.py')):
        if path.is_relative_to(_PROFILE_DIRECTORY) is True:
            continue
        for module in _imported_modules(path):
            if module.startswith('pydtcpip.dlna.profiles.') is True:
                pytest.fail(f'{path.relative_to(_PACKAGE_DIRECTORY)} imports {module} directly')


def test_every_profile_is_registered_and_named_after_its_file() -> None:
    # Unregistered profiles cannot be selected, and mismatched names make profiles hard to find
    registered_names = {profile.name for profile in PROFILES}
    for path in sorted(_PROFILE_DIRECTORY.glob('*.py')):
        if path.name in ('__init__.py', 'base.py'):
            continue
        assert path.stem in registered_names, f'{path.stem} is not registered in PROFILES'


@pytest.mark.parametrize(('vendor', 'model'), _fixture_devices())
def test_each_fixture_matches_exactly_one_deepest_profile(vendor: str, model: str) -> None:
    # Two matches at the same depth could make a new profile take over an existing device
    raw_xml = (_FIXTURE_DIRECTORY / vendor / model / 'description.xml').read_text(encoding='utf-8')
    description = parse_device_description('http://192.0.2.1/description.xml', raw_xml)
    matched = [profile for profile in PROFILES if profile.is_match(description) is True]
    deepest_depth = max(profile.depth for profile in matched)
    deepest = [profile.name for profile in matched if profile.depth == deepest_depth]
    assert len(deepest) == 1, f'{vendor}/{model} matches multiple profiles at the same depth: {deepest}'
    assert deepest[0] == vendor


@pytest.mark.parametrize(('vendor', 'model'), _fixture_devices())
def test_fixture_recordings_keep_their_protection_values(vendor: str, model: str) -> None:
    # Detect changes to values parsed from saved device responses
    device_directory = _FIXTURE_DIRECTORY / vendor / model
    description = parse_device_description(
        'http://192.0.2.1/description.xml', (device_directory / 'description.xml').read_text(encoding='utf-8')
    )
    profile = select_profile(description)
    objects = parse_didl((device_directory / 'recording.xml').read_text(encoding='utf-8'), profile)
    recordings = [item for item in objects if isinstance(item, Recording)]
    assert len(recordings) == 1

    expected_profile, expected_status, expected_value, expected_ci = _EXPECTED[(vendor, model)]
    assert profile.name == expected_profile
    assert recordings[0].protection.remaining_copy_count.status == expected_status
    assert recordings[0].protection.remaining_copy_count.value == expected_value

    # Prefer the original resource (DLNA.ORG_CI=0) over a transcoded resource
    original = recordings[0].original_resource
    assert original is not None
    assert original.protocol_info.parameters.get('DLNA.ORG_CI') == expected_ci


def test_generic_profile_handles_standard_dlna_without_vendor_meaning() -> None:
    # Detect changes to standard behavior for devices that match no family
    description = parse_device_description(
        'http://192.0.2.1/description.xml',
        '<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
        '<deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType><friendlyName>標準の機器</friendlyName>'
        '<manufacturer>Example</manufacturer><modelName>Example Server</modelName><UDN>uuid:00000000-0000-0000-0000-000000000001</UDN>'
        '</device></root>',
    )
    profile = select_profile(description)
    assert profile is GENERIC

    didl = (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<container id="1" parentID="0" childCount="2"><dc:title>録画</dc:title><upnp:class>object.container</upnp:class></container>'
        '<item id="2" parentID="1"><dc:title>番組</dc:title><upnp:class>object.item.videoItem</upnp:class>'
        '<upnp:genre>ニュース</upnp:genre><upnp:genre>報道</upnp:genre>'
        '<res protocolInfo="http-get:*:application/x-dtcp1;DTCP1HOST=192.0.2.1;DTCP1PORT=5000:DLNA.ORG_CI=0;DTCP.COM_FLAGS=C0000000">http://192.0.2.1/2</res>'
        '</item></DIDL-Lite>'
    )
    objects = parse_didl(didl, profile)
    assert [type(item).__name__ for item in objects] == ['Container', 'Recording']
    recording = objects[1]
    assert isinstance(recording, Recording)
    assert recording.genres == ('ニュース', '報道')
    assert recording.protection.remaining_copy_count.status == 'unsupported'
    assert recording.protection.is_move_supported.value is True
    assert recording.protection.is_transaction_move_supported.value is True
    assert profile.resolve_http_status()(403, 'http://192.0.2.1/2') is None


def _panasonic_copy_count(res_attributes: str) -> tuple[str, int | None]:
    """
    Read the copy count that the Panasonic profile derives from one res element.

    Args:
        res_attributes (str): Attributes to place on the res element

    Returns:
        tuple[str, int | None]: Status and value
    """

    didl = (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:pxn="urn:schemas-panasonic-com:pxn">'
        '<item id="1" parentID="0"><dc:title>伏せた値</dc:title>'
        '<upnp:class>object.item.videoItem</upnp:class>'
        f'<res protocolInfo="http-get:*:application/x-dtcp1;DTCP1PORT=60010" {res_attributes}>'
        'http://192.0.2.1:60001/1</res></item></DIDL-Lite>'
    )
    objects = parse_didl(didl, PANASONIC)
    recording = objects[0]
    assert isinstance(recording, Recording)
    count = recording.protection.remaining_copy_count
    return count.status, count.value


@pytest.mark.parametrize(
    ('res_attributes', 'expected'),
    [
        pytest.param('pxn:CopyCount="10"', ('known', 9), id='unused-dubbing-10'),
        pytest.param('pxn:CopyCount="9"', ('known', 8), id='one-copy-used'),
        pytest.param('pxn:CopyCount="1"', ('known', 0), id='only-the-final-move-remains'),
        pytest.param('', ('omitted', None), id='absent'),
        pytest.param('pxn:CopyCount="0"', ('unsupported', None), id='zero'),
        pytest.param('pxn:CopyCount="many"', ('unsupported', None), id='not-a-number'),
    ],
)
def test_panasonic_copy_count_excludes_the_final_move(res_attributes: str, expected: tuple[str, int | None]) -> None:
    # A device that counts the final Move must not look like it has an extra copy
    assert _panasonic_copy_count(res_attributes) == expected


def test_panasonic_copy_count_reports_disagreeing_resources_as_unsupported() -> None:
    # Silently picking one of two different values would misstate the remaining copies
    didl = (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:pxn="urn:schemas-panasonic-com:pxn">'
        '<item id="1" parentID="0"><dc:title>伏せた値</dc:title>'
        '<upnp:class>object.item.videoItem</upnp:class>'
        '<res protocolInfo="http-get:*:application/x-dtcp1;DTCP1PORT=60010" pxn:CopyCount="10">http://192.0.2.1/1</res>'
        '<res protocolInfo="http-get:*:application/x-dtcp1;DTCP1PORT=60010" pxn:CopyCount="9">http://192.0.2.1/2</res>'
        '</item></DIDL-Lite>'
    )
    recordings = [item for item in parse_didl(didl, PANASONIC) if isinstance(item, Recording)]
    assert recordings[0].protection.remaining_copy_count.status == 'unsupported'


def test_panasonic_reads_recordings_from_their_parent_listing() -> None:
    # pxn:CopyCount appears only in BrowseDirectChildren, so metadata responses lack the copy count
    assert PANASONIC.resolve_has_listing_only_metadata() is True


def test_sie_nasne_reports_client_registration_refusal() -> None:
    # Distinguish nasne's 403 from authentication failures so users can find client registration
    error = SIE_NASNE.resolve_http_status()(403, 'http://192.0.2.1/2')
    assert isinstance(error, ClientNotAllowedError)
    assert 'Client Device Management' in str(error)
    assert SIE_NASNE.resolve_http_status()(404, 'http://192.0.2.1/2') is None
