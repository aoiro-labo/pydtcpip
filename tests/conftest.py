"""Shared test fixtures."""

import pytest

from tests.fakes import FakeAuthority, FakeDevice


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests with asyncio."""

    return 'asyncio'


@pytest.fixture
def authority(monkeypatch: pytest.MonkeyPatch) -> FakeAuthority:
    """Replace DTLA public keys with a generated test authority key."""

    authority = FakeAuthority.generate()
    monkeypatch.setattr('pydtcpip.dtcp.crypto._AUTHORITY_KEYS', (authority.public_key,))
    return authority


@pytest.fixture
def sink_device(authority: FakeAuthority) -> FakeDevice:
    """Sink device certificate and private key."""

    return authority.issue_device(0x0102030405)


@pytest.fixture
def source_device(authority: FakeAuthority) -> FakeDevice:
    """Source device certificate and private key."""

    return authority.issue_device(0x0A0B0C0D0E)
