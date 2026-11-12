"""DTCP elliptic curve, device certificates, and content keys."""

import hashlib
from typing import Self, cast

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from ecdsa import BadSignatureError, MalformedPointError, SigningKey, VerifyingKey
from ecdsa.curves import Curve
from ecdsa.ellipticcurve import CurveFp, Point
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pydtcpip.errors import DTCPError


# DTCP's curve is not named by OpenSSL, so use ecdsa for arbitrary curve support
_FIELD = CurveFp(
    0x94A8E16AAD4F50EFE29B9D5C0C0B6D481B27DE53,
    0x94A8E16AAD4F50EFE29B9D5C0C0B6D481B27DE50,
    0x04FD918E5B0C4513FA3EF3033FE08F07C3B08C76D,
)
_ORDER = 0x02278C8AD247A46B5C53DE4CC9A0072488F028A3
_GENERATOR = Point(
    _FIELD,
    0x078668913DEAB22759E587EB393D7DA46CE24B196,
    0x4D2BA996A7E3D9AF4D266AFE00443B95D6870606,
    _ORDER,
)
DTCP_CURVE = Curve('DTCP', _FIELD, _GENERATOR, None)

# DTLA public keys used to sign device certificates and SRMs
## Tests replace these with a test authority's keys to connect source and sink in one process
_AUTHORITY_KEYS: tuple[bytes, ...] = (
    bytes.fromhex('6e6e94c45dbedd467e42b789cce95cd19abcc2cc35d26bc0dff1dfeb2857088e052c5d9b2b339ad5'),
    bytes.fromhex('23b8461648aa748babae9d9bd905c7ab40ea8efa743f1b3bb1fc17fbb952ad4f84f1f39a886a59b7'),
)

# Constants appended to the exchange key for content key derivation, indexed by E-EMI
_CONTENT_CONSTANTS = {
    0x2: bytes.fromhex('de665adec0156112cf2628eb'),
    0x4: bytes.fromhex('45b146a0611a501ac32bfad4'),
    0x6: bytes.fromhex('e6ed3e3078ff0e5b3a273ccb'),
    0x8: bytes.fromhex('7c0d87c76c195662f98c14e6'),
    0xA: bytes.fromhex('28b522c7cdb22d490ef8e3d4'),
    0xC: bytes.fromhex('a3806f971635c1796deaed24'),
}
_IV_CONSTANT = bytes.fromhex('95dc3a449028eb3c')


def verify_authority_signature(data: bytes, signature: bytes) -> None:
    """
    Verify a device certificate or SRM signature using DTLA public keys.

    Args:
        data (bytes): Signed bytes
        signature (bytes): ECDSA signature consisting of two concatenated 20-byte integers
    """

    # Either of the two DTLA public keys can verify the signature
    for public_key in _AUTHORITY_KEYS:
        verifier = VerifyingKey.from_string(public_key, curve=DTCP_CURVE, hashfunc=hashlib.sha1)
        try:
            verifier.verify(signature, data, hashfunc=hashlib.sha1)
        except BadSignatureError:
            continue
        return
    raise DTCPError('Could not verify the DTLA signature.')


def verify_certificate(certificate: bytes) -> VerifyingKey:
    """
    Verify a device certificate and return its public key.

    Args:
        certificate (bytes): 88-byte baseline certificate

    Returns:
        VerifyingKey: Public key for verifying device signatures
    """

    # Baseline certificates have type 1 and support at most SRM generation 1 (upper four bits)
    if len(certificate) != 88 or certificate[0] != 1 or certificate[1] >> 4 > 1:
        raise DTCPError('The device certificate must be an 88-byte DTCP baseline certificate.')
    verify_authority_signature(certificate[:48], certificate[48:])
    try:
        return VerifyingKey.from_string(certificate[8:48], curve=DTCP_CURVE, hashfunc=hashlib.sha1)
    except MalformedPointError as ex:
        raise DTCPError('The device certificate contains an invalid public key.') from ex


def device_id_of(certificate: bytes) -> int:
    """
    Extract the 5-byte device ID used for SRM revocation checks.

    Args:
        certificate (bytes): 88-byte baseline certificate

    Returns:
        int: Device ID
    """

    return int.from_bytes(certificate[3:8], 'big')


class DeviceCredentials(BaseModel):
    """
    The sink's device certificate and private key for DTCP-IP mutual authentication.
    Construction verifies the certificate signature and checks that the private key matches its public key.
    Storage is up to the caller; provide both values as bytes.
    """

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    certificate: bytes
    private_key: bytes = Field(repr=False)

    @model_validator(mode='after')
    def _verify(self) -> Self:
        """
        Verify the certificate signature and matching private key.

        Returns:
            Self: Validated credentials
        """

        # Verify the supplied certificate signature and matching private key at this boundary
        verifier = verify_certificate(self.certificate)
        if len(self.private_key) != 20:
            raise ValueError('The device private key must be 20 bytes.')
        try:
            signer = SigningKey.from_string(self.private_key, curve=DTCP_CURVE, hashfunc=hashlib.sha1)
        except MalformedPointError as ex:
            raise ValueError('The device private key is outside the DTCP key range.') from ex
        # ecdsa lacks type annotations, so explicitly type the public key derived from the private key
        if cast(VerifyingKey, signer.get_verifying_key()).to_string() != verifier.to_string():
            raise ValueError('The device private key does not match the certificate public key.')
        return self

    @property
    def max_srm_generation(self) -> int:
        """Return the maximum SRM generation this device can store."""

        return self.certificate[1] >> 4


def derive_content_key(exchange_key: bytes, encryption_mode: int, nonce: bytes) -> tuple[bytes, bytes]:
    """
    Derive the AES content key and CBC initialization vector from the exchange key and PCP nonce.

    Args:
        exchange_key (bytes): 12-byte exchange key received during authentication
        encryption_mode (int): PCP E-EMI
        nonce (bytes): 8-byte content nonce from the PCP

    Returns:
        tuple[bytes, bytes]: 16-byte content key and 16-byte initialization vector
    """

    if len(exchange_key) != 12 or len(nonce) != 8:
        raise DTCPError('The exchange key must be 12 bytes and the content nonce must be 8 bytes.')
    constant = _CONTENT_CONSTANTS.get(encryption_mode)
    if constant is None:
        raise DTCPError(f'Unsupported content encryption mode (E-EMI: 0x{encryption_mode:x}).')

    # Concatenate the exchange key, mode constant, and nonce; XOR the second block's ciphertext and plaintext
    material = exchange_key + constant + nonce
    encryptor = Cipher(algorithms.AES128(material[:16]), modes.ECB()).encryptor()
    block = encryptor.update(material[16:]) + encryptor.finalize()
    content_key = bytes(a ^ b for a, b in zip(block, material[16:], strict=True))

    # Encrypt the constant and nonce with the content key to obtain the initialization vector
    encryptor = Cipher(algorithms.AES128(content_key), modes.ECB()).encryptor()
    iv = encryptor.update(_IV_CONSTANT + nonce) + encryptor.finalize()
    return content_key, iv
