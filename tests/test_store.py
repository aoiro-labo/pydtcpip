"""Verify credential selection and SRM persistence through the public API."""

import os
from pathlib import Path

import pytest

from pydtcpip import DeviceStore, DTCPClient
from tests.fakes import FakeAuthority, FakeDevice, FakeMediaServer, FakeSourceAKE


def test_credentials_file_and_environment_priority(
    sink_device: FakeDevice, source_device: FakeDevice, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credential precedence must select the intended device certificate."""

    monkeypatch.delenv('PYDTCPIP_CERTIFICATE', raising=False)
    monkeypatch.delenv('PYDTCPIP_PRIVATE_KEY', raising=False)
    store = DeviceStore(data_dir=tmp_path)
    (tmp_path / 'credentials.env').write_text(
        f'PYDTCPIP_CERTIFICATE={sink_device.certificate.hex()}\nPYDTCPIP_PRIVATE_KEY={sink_device.private_key.hex()}\n',
        encoding='utf-8',
    )
    other_file = tmp_path / 'other.env'
    other_file.write_text(
        f'PYDTCPIP_CERTIFICATE={source_device.certificate.hex()}\n'
        f'PYDTCPIP_PRIVATE_KEY={source_device.private_key.hex()}\n',
        encoding='utf-8',
    )

    assert store.load_credentials() == sink_device.credentials()
    assert store.load_credentials(other_file) == source_device.credentials()
    monkeypatch.setenv('PYDTCPIP_CERTIFICATE', sink_device.certificate.hex())
    monkeypatch.setenv('PYDTCPIP_PRIVATE_KEY', sink_device.private_key.hex())
    assert store.load_credentials(other_file) == sink_device.credentials()
    assert DeviceStore(tmp_path / 'empty').load_credentials() == sink_device.credentials()
    # Report an invalid explicit path even when environment credentials are available
    with pytest.raises(FileNotFoundError):
        store.load_credentials(tmp_path / 'missing.env')


def test_invalid_credentials_do_not_expose_private_key(
    sink_device: FakeDevice, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid credentials must not expose the private key in application exception logs."""

    monkeypatch.setenv('PYDTCPIP_CERTIFICATE', sink_device.certificate.hex())
    secret = b'PRIVATE_KEY_INVALID'
    monkeypatch.setenv('PYDTCPIP_PRIVATE_KEY', secret.hex())
    with pytest.raises(ValueError) as raised:
        DeviceStore(tmp_path).load_credentials()
    assert secret.hex() not in str(raised.value)
    assert secret.decode() not in str(raised.value)


@pytest.mark.anyio
async def test_store_authenticates_and_reuses_received_srm(
    authority: FakeAuthority,
    sink_device: FakeDevice,
    source_device: FakeDevice,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticate using CLI credential files and reuse a received SRM in a later client."""

    monkeypatch.delenv('PYDTCPIP_CERTIFICATE', raising=False)
    monkeypatch.delenv('PYDTCPIP_PRIVATE_KEY', raising=False)
    store = DeviceStore(tmp_path / 'device')
    store.data_dir.mkdir()
    (store.data_dir / 'credentials.env').write_text(
        f'PYDTCPIP_CERTIFICATE={sink_device.certificate.hex()}\nPYDTCPIP_PRIVATE_KEY={sink_device.private_key.hex()}\n',
        encoding='utf-8',
    )
    srm_data = authority.issue_srm(2)
    content = b'recording content' * 1000
    received = bytearray()

    async def on_data(chunk: bytes) -> None:
        received.extend(chunk)

    assert store.load_srm() is None
    async with (
        FakeSourceAKE(authority, source_device, srm=srm_data) as source,
        FakeMediaServer(source, content) as server,
    ):
        for _ in range(2):
            # A new instance can load the previously saved information from the same directory
            reopened = DeviceStore(store.data_dir)
            async with DTCPClient(
                reopened.load_credentials(),
                srm=reopened.load_srm(),
                on_srm_update=reopened.save_srm,
                timeout=5,
            ) as client:
                await client.stream(server.url, on_data)

    assert received == content * 2
    assert (store.data_dir / 'srm.bin').read_bytes() == srm_data
    saved_srm = store.load_srm()
    assert saved_srm is not None and saved_srm.version == 2
    assert DeviceStore(tmp_path / 'other-device').load_srm() is None
    if os.name != 'nt':
        assert (store.data_dir / 'srm.bin').stat().st_mode & 0o777 == 0o600
    assert source.errors == []
