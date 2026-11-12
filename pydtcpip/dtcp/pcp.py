"""Read and decrypt DTCP-IP protected packets (PCP) independently of HTTP chunk boundaries."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import BaseModel, ConfigDict

from pydtcpip.dtcp.crypto import derive_content_key
from pydtcpip.errors import DTCPError


PCP_HEADER_SIZE = 14
_BLOCK_SIZE = 16
# Maximum PCP content length from the DTCP-IP specification, preventing oversized reads from corrupt lengths
_MAX_CONTENT_LENGTH = 128 * 1024 * 1024


class ExactReader(Protocol):
    """Async reader that reads an exact byte count, such as an aiohttp or asyncio StreamReader."""

    async def readexactly(self, n: int) -> bytes: ...


class ProtectedPacket(BaseModel):
    """
    A DTCP-IP protected packet.
    wire_bytes contains the 14-byte header and encrypted data including padding.
    """

    model_config = ConfigDict(frozen=True)

    wire_bytes: bytes

    @property
    def packet_type(self) -> int:
        """Return the type in the first two header bits (0 for PCP)."""

        return self.wire_bytes[0] >> 6

    @property
    def cipher_algorithm(self) -> int:
        """Return the two-bit cipher algorithm (C_A) from the header."""

        return (self.wire_bytes[0] >> 4) & 0x3

    @property
    def encryption_mode(self) -> int:
        """Return the E-EMI indicating copy control during transfer."""

        return self.wire_bytes[0] & 0x0F

    @property
    def exchange_key_label(self) -> int:
        """Return the label of the exchange key used for encryption."""

        return self.wire_bytes[1]

    @property
    def nonce(self) -> bytes:
        """Return the 8-byte nonce used to derive the content key."""

        return self.wire_bytes[2:10]

    @property
    def content_length(self) -> int:
        """Return the content length excluding encryption padding."""

        return int.from_bytes(self.wire_bytes[10:PCP_HEADER_SIZE], 'big')


async def read_packets(reader: ExactReader) -> AsyncIterator[ProtectedPacket]:
    """
    Read PCPs one at a time from an HTTP body.
    End normally at a packet boundary and raise DTCPError if the body ends within a packet.
    The caller must determine at the HTTP layer whether the entire body arrived.

    Args:
        reader (ExactReader): HTTP body reader

    Yields:
        ProtectedPacket: Packet read from the body
    """

    while True:
        # Only an end of body at the start of a header is a normal end to the PCP sequence
        try:
            header = await reader.readexactly(PCP_HEADER_SIZE)
        except asyncio.IncompleteReadError as ex:
            if len(ex.partial) == 0:
                return
            raise DTCPError(
                f'The protected packet header is truncated ({len(ex.partial)} / {PCP_HEADER_SIZE} bytes).'
            ) from ex

        if header[0] >> 6 != 0:
            raise DTCPError('Received a packet that is not a DTCP-IP PCP.')
        content_length = int.from_bytes(header[10:PCP_HEADER_SIZE], 'big')
        if content_length > _MAX_CONTENT_LENGTH:
            raise DTCPError(f'The protected packet content length exceeds the limit ({content_length} bytes).')

        # Encrypted data is padded to a multiple of the AES block size
        encrypted_length = (content_length + _BLOCK_SIZE - 1) // _BLOCK_SIZE * _BLOCK_SIZE
        try:
            body = await reader.readexactly(encrypted_length)
        except asyncio.IncompleteReadError as ex:
            raise DTCPError(
                f'The protected packet is truncated ({len(ex.partial)} / {encrypted_length} bytes).'
            ) from ex
        yield ProtectedPacket(wire_bytes=header + body)


def decrypt_packet(packet: ProtectedPacket, exchange_key: bytes) -> bytes:
    """
    Decrypt a PCP using the exchange key and return its content without padding.
    The caller holding the key is responsible for checking its label.

    Args:
        packet (ProtectedPacket): PCP returned by read_packets()
        exchange_key (bytes): 12-byte exchange key received during authentication

    Returns:
        bytes: Content from the source (TS packets are not transformed)
    """

    content_key, iv = derive_content_key(exchange_key, packet.encryption_mode, packet.nonce)
    decryptor = Cipher(algorithms.AES128(content_key), modes.CBC(iv)).decryptor()
    cleartext = decryptor.update(packet.wire_bytes[PCP_HEADER_SIZE:]) + decryptor.finalize()
    return cleartext[: packet.content_length]
