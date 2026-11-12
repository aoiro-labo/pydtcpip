"""
Compare content key derivation and Move finalization MACs with values from calculations used successfully with a device.
The fake source shares content key derivation with the sink, so this detects errors an in-process exchange cannot.
"""

import asyncio

import pytest

from pydtcpip.dtcp.ake import ExchangeKey
from pydtcpip.dtcp.crypto import derive_content_key
from pydtcpip.dtcp.move import MoveTransaction
from pydtcpip.errors import DTCPError


# Content keys and IVs by E-EMI for exchange key bytes(range(12)) and nonce bytes(range(0x80, 0x88))
## The calculation successfully decrypted data received from a device
_CONTENT_KEYS = {
    0x2: '49cab6fb54b954f726cb09dbe1462e0aa5a4aa2f3f98e71af8f8287fecaeb98a',
    0x4: 'e5110b3440d24f5d3355eee3d0dad360b4610f63105289524d339d212f8ea3f7',
    0x6: 'be59c30062fb6e6f99307e076d990cacda84cd388fa6f92c4322a1c66a3c45b7',
    0x8: '3c2f018f0ae58945a523d6a30aa3202aca0d8636060299087a08f77d30cb073f',
    0xA: 'e5ef555cb40826c4fffbd9987c20fa4840a8153b77da41f27ca8a9fcb8bd3121',
    0xC: '16ecd1ea4ea71f1e63d57f70d4e1e75ff413b4df4e28df70570809fab0bd941b',
}

# Finalize MACs for exchange key bytes(range(12)), label 0xAB, and nonce 1011121314151617
## The calculation successfully finalized a Move with a device
_FINALIZE_NONCE = bytes.fromhex('1011121314151617')
_FINALIZE_REQUEST_MAC = bytes.fromhex('300076263a78249402b4')
_FINALIZE_RESPONSE_MAC = bytes.fromhex('99b439911b6907eb5e8c')


@pytest.mark.parametrize('encryption_mode', sorted(_CONTENT_KEYS))
def test_derive_content_key_matches_interoperable_values(encryption_mode: int) -> None:
    """Incorrect E-EMI constants or key construction prevents decryption of recorder data."""

    content_key, iv = derive_content_key(bytes(range(12)), encryption_mode, bytes(range(0x80, 0x88)))
    assert (content_key + iv).hex() == _CONTENT_KEYS[encryption_mode]


@pytest.mark.anyio
@pytest.mark.parametrize('is_corrupt', [False, True])
async def test_finalize_matches_interoperable_mac(monkeypatch: pytest.MonkeyPatch, is_corrupt: bool) -> None:
    """Verify the request MAC and reject a corrupt response MAC."""

    # Use a fixed finalize nonce
    def fixed_nonce(size: int) -> bytes:
        return _FINALIZE_NONCE

    monkeypatch.setattr('pydtcpip.dtcp.move.secrets.token_bytes', fixed_nonce)
    received: list[bytes] = []

    # Return a fixed acceptance MAC after recording the finalize request
    response_mac = _FINALIZE_RESPONSE_MAC
    if is_corrupt is True:
        response_mac = bytes((response_mac[0] ^ 1,)) + response_mac[1:]

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        prefix = await reader.readexactly(3)
        received.append(prefix + await reader.readexactly(int.from_bytes(prefix[1:3], 'big')))
        payload = bytes((0xAB,)) + _FINALIZE_NONCE + response_mac
        writer.write(bytes((0x01, 0x00, 8 + len(payload), 0x09, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00)) + payload)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    async with server:
        port = int(server.sockets[0].getsockname()[1])
        transaction = MoveTransaction(
            '127.0.0.1', port, ExchangeKey(value=bytes(range(12)), label=0xAB), transfer_id='test', timeout=5
        )
        transaction.has_received_all = True
        if is_corrupt is True:
            with pytest.raises(DTCPError, match='MAC'):
                await transaction.finalize()
            # After sending finalization, remain ready to retry rather than cancel if verification fails
            assert transaction.state == 'finalizing'
        else:
            await transaction.finalize()
            assert transaction.state == 'finalized'
        await transaction.close()

    # The control header is followed by the key label, nonce, and request MAC
    assert received == [
        bytes.fromhex('01001b000022000000000f') + bytes((0xAB,)) + _FINALIZE_NONCE + _FINALIZE_REQUEST_MAC
    ]
