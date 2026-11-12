"""Connection-independent models for recordings, resources, and protection information."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Protection information acquisition status
## known: the value was obtained from a response or packet
## not_observed: the step that obtains the information has not yet been reached
## omitted: the response was obtained but the field was absent
## unsupported: the library cannot parse the information's format
type AcquisitionStatus = Literal['known', 'not_observed', 'omitted', 'unsupported']

# Protection information source
## metadata: DIDL-Lite recording listing, including device-specific elements
## protocol_info: resource protocolInfo
## http_header: media HTTP response header
## pcp_header: received protected packet (PCP) header
type ProtectionSource = Literal['metadata', 'protocol_info', 'http_header', 'pcp_header']


class ProtectionValue[T](BaseModel):
    """
    A protection value with its source, observation time, and acquisition status.
    Values omitted by the device remain distinct from zero and unsupported values.
    """

    model_config = ConfigDict(frozen=True)

    status: AcquisitionStatus
    value: T | None = None
    source: ProtectionSource
    observed_at: datetime | None = None


class TimeRange(BaseModel):
    """A time range in milliseconds from the start of the media."""

    model_config = ConfigDict(frozen=True)

    start_ms: int
    end_ms: int | None = None

    @model_validator(mode='after')
    def _validate(self) -> Self:
        """
        Validate the start and end of the time range.

        Returns:
            Self: Validated time range
        """

        if self.start_ms < 0 or (self.end_ms is not None and self.end_ms < self.start_ms):
            raise ValueError('The time range must start at or after zero and end at or after the start.')
        return self

    def to_header(self) -> str:
        """
        Convert to a DLNA TimeSeekRange.dlna.org header value (NPT with three decimal places).

        Returns:
            str: Value in the form `npt=60.000-90.000`
        """

        start_seconds, start_fraction = divmod(self.start_ms, 1000)
        start = f'npt={start_seconds}.{start_fraction:03d}-'
        if self.end_ms is None:
            return start
        end_seconds, end_fraction = divmod(self.end_ms, 1000)
        return f'{start}{end_seconds}.{end_fraction:03d}'


class ProtocolInfo(BaseModel):
    """Parsed resource protocolInfo (`<protocol>:<network>:<MIME type>:<additional info>`)."""

    model_config = ConfigDict(frozen=True)

    raw: str
    protocol: str
    network: str
    content_type: str
    # Semicolon-separated `name=value` pairs in the fourth field (e.g. DLNA.ORG_PN, DLNA.ORG_CI, DTCP.COM_FLAGS)
    parameters: dict[str, str]
    # Parameters following the MIME type (e.g. DTCP1HOST, DTCP1PORT, CONTENTFORMAT)
    content_type_parameters: dict[str, str]

    @property
    def is_dtcp(self) -> bool:
        """Return whether the resource is protected by DTCP-IP."""

        return self.content_type == 'application/x-dtcp1'

    @property
    def is_converted(self) -> bool | None:
        """
        Return whether the recorder converted this resource.
        DLNA.ORG_CI=1 indicates a conversion and 0 the stored format; return None if omitted.
        """

        value = self.parameters.get('DLNA.ORG_CI')
        if value is None:
            return None
        return value == '1'


class Resource(BaseModel):
    """A recording resource (a DIDL-Lite res element)."""

    model_config = ConfigDict(frozen=True)

    url: str
    protocol_info: ProtocolInfo
    # res attributes (namespaced attributes use the `{namespace}name` format)
    attributes: dict[str, str]
    raw_xml: str

    @property
    def size(self) -> int | None:
        """Return the HTTP body size from res@size in bytes (None if absent)."""

        value = self.attributes.get('size')
        if value is None or value.isdecimal() is False:
            return None
        return int(value)

    @property
    def cleartext_size(self) -> int | None:
        """Return the decrypted content size from dlna:cleartextSize in bytes (None if absent)."""

        value = self.attributes.get('{urn:schemas-dlna-org:metadata-1-0/}cleartextSize')
        if value is None or value.isdecimal() is False:
            return None
        return int(value)


class RecordingProtection(BaseModel):
    """
    Protection information available from a recording listing.
    Transfer copy control (E-EMI) is known only after reception starts and is reported separately.
    """

    model_config = ConfigDict(frozen=True)

    # Copies remaining on the source, obtained from a recorder-specific element
    ## Like the TV display, this excludes the final Move: 0 means only a Move remains (9 for unused Dubbing 10)
    remaining_copy_count: ProtectionValue[int]
    # DTCP.COM_FLAGS bit 31: Move support
    is_move_supported: ProtectionValue[bool]
    # DTCP.COM_FLAGS bit 30: transaction-based Move support
    is_transaction_move_supported: ProtectionValue[bool]


class Container(BaseModel):
    """A recorder folder, with ARIB text normalized in metadata and raw_xml."""

    model_config = ConfigDict(frozen=True)

    id: str
    parent_id: str
    title: str
    upnp_class: str
    child_count: int | None
    raw_xml: str


class Recording(BaseModel):
    """A recorder's recording and resources, with ARIB text normalized in metadata and raw_xml."""

    model_config = ConfigDict(frozen=True)

    id: str
    parent_id: str
    title: str
    upnp_class: str
    description: str | None
    long_description: str | None
    channel_name: str | None
    genres: tuple[str, ...]
    # Broadcast start and duration as reported by the device (format varies by device)
    date: str | None
    duration: str | None
    resources: tuple[Resource, ...]
    protection: RecordingProtection
    raw_xml: str

    @property
    def original_resource(self) -> Resource | None:
        """
        Return a DTCP-IP resource in the recorder's stored format.
        Prefer DLNA.ORG_CI=0; otherwise return the first resource not explicitly marked as converted.
        """

        dtcp_resources = [resource for resource in self.resources if resource.protocol_info.is_dtcp is True]
        for resource in dtcp_resources:
            if resource.protocol_info.is_converted is False:
                return resource
        for resource in dtcp_resources:
            if resource.protocol_info.is_converted is None:
                return resource
        return None


class MediaInfo(BaseModel):
    """DTCP-IP authentication endpoint and transfer information from a media HTTP response."""

    model_config = ConfigDict(frozen=True)

    url: str
    # Source address and port for DTCP-IP mutual authentication
    host: str
    port: int
    content_type: str
    content_format: str | None
    content_features: str | None
    # HTTP body size in bytes (None if unknown, e.g. with chunked encoding)
    content_length: int | None
    # Time range actually returned by the server (TimeSeekRange.dlna.org value)
    time_range: str | None
    headers: dict[str, str]


class MoveResumeState(BaseModel):
    """
    Information for resuming finalization of the same Move after losing its response.
    This contains an exchange key and must be stored where only its owner can read it.
    """

    # Serialize the exchange key and nonce as Base64 strings in JSON
    model_config = ConfigDict(frozen=True, ser_json_bytes='base64', val_json_bytes='base64')

    host: str
    port: int
    exchange_key: bytes = Field(repr=False)
    exchange_key_label: int
    # Nonce for finalization (reuse the same value when retrying the same transfer)
    nonce: bytes = Field(repr=False)
    # finalizing: immediately before the request, or sent without receiving a response
    # finalized: finalize response verified, completion notification not yet sent
    state: Literal['finalizing', 'finalized']
    written_bytes: int
