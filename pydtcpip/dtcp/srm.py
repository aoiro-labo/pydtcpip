"""Verify DTLA-signed revocation information (SRM) and check device revocation."""

from typing import Self

from pydantic import BaseModel, ConfigDict

from pydtcpip.dtcp.crypto import device_id_of, verify_authority_signature
from pydtcpip.errors import DTCPError


class SRM(BaseModel):
    """
    A signature-verified System Renewability Message (SRM) and its revoked device ID ranges.
    A receiver without an SRM authenticates using version 0 and receives a newer version from its peer.
    """

    model_config = ConfigDict(frozen=True)

    # Complete SRM received from the source or supplied by the user (empty if unavailable)
    data: bytes = b''
    version: int = 0
    # Last generation present (0 if only the first part is present)
    generation: int = 0
    # Revoked device ID ranges, inclusive
    revoked_ranges: tuple[tuple[int, int], ...] = ()

    @classmethod
    def parse(cls, data: bytes) -> Self:
        """
        Verify each generation's cumulative signature and read individual and range revocations.

        Args:
            data (bytes): SRM supplied by the user or received from a peer

        Returns:
            SRM: Signature-verified SRM
        """

        if not 46 <= len(data) <= 1024 or data[0] > 1 or data[1] != 0:
            raise DTCPError('Invalid SRM header.')

        position = 4
        generation = -1
        revoked_ranges: list[tuple[int, int]] = []
        while position < len(data):
            # Each generation contains a length, revocation list, and signature
            generation += 1
            if generation > data[0] or position + 2 > len(data):
                raise DTCPError('Invalid SRM generation count or length.')
            size = int.from_bytes(data[position : position + 2], 'big')
            end = position + size
            maximum_size = 124 if generation == 0 else 978
            if not 42 <= size <= maximum_size or end > len(data):
                raise DTCPError('Invalid SRM revocation list and signature length.')

            # The second part's signature covers everything preceding it, including the first signature
            signature_start = end - 40
            verify_authority_signature(data[:signature_start], data[signature_start:end])

            # Entries contain individual device IDs (5 bytes), or a starting ID and count (7 bytes)
            position += 2
            while position < signature_start:
                header = data[position]
                position += 1
                entry_type, count = header >> 5, header & 0x1F
                if entry_type not in (0, 1):
                    raise DTCPError('Unsupported revocation list format.')
                width = 5 if entry_type == 0 else 7
                if position + count * width > signature_start:
                    raise DTCPError('The revoked device ID list is truncated.')
                for _ in range(count):
                    first = int.from_bytes(data[position : position + 5], 'big')
                    span = 0
                    if entry_type == 1:
                        span = int.from_bytes(data[position + 5 : position + 7], 'big')
                    revoked_ranges.append((first, first + span))
                    position += width
            position = end

        return cls(
            data=data,
            version=int.from_bytes(data[2:4], 'big'),
            generation=generation,
            revoked_ranges=tuple(revoked_ranges),
        )

    def is_newer_than(self, other: Self) -> bool:
        """
        Compare SRM version and stored extent to determine which is newer.

        Args:
            other (SRM): SRM to compare

        Returns:
            bool: True if this SRM is newer
        """

        return (self.version, len(self.data)) > (other.version, len(other.data))

    def check_device(self, certificate: bytes) -> None:
        """
        Reject a certificate whose device ID is on the revocation list.

        Args:
            certificate (bytes): Signature-verified baseline certificate
        """

        device_id = device_id_of(certificate)
        for first, last in self.revoked_ranges:
            if first <= device_id <= last:
                raise DTCPError('The device certificate is revoked by the SRM.')
