"""Discover DLNA media servers on a home network and browse recordings."""

import asyncio
import logging
from types import TracebackType
from typing import Self

import aiohttp
from pydantic import BaseModel, ConfigDict

from pydtcpip.dlna.description import DeviceDescription, ServiceInfo, parse_device_description
from pydtcpip.dlna.didl import parse_didl
from pydtcpip.dlna.profiles import Profile, select_profile
from pydtcpip.dlna.soap import SOAPResult, call_action
from pydtcpip.dlna.ssdp import MEDIA_SERVER_DEVICE_TYPE, search
from pydtcpip.errors import DLNAError
from pydtcpip.models import Container, Recording


_LOGGER = logging.getLogger(__name__)

_CONTENT_DIRECTORY = 'urn:schemas-upnp-org:service:ContentDirectory:'

# Number of entries requested per Browse when fetching all pages
## Device limits vary and some return fewer than requested, so advance by the actual count
_BROWSE_PAGE_SIZE = 100


class BrowseResult(BaseModel):
    """Result of one Browse request."""

    model_config = ConfigDict(frozen=True)

    objects: tuple[Container | Recording, ...]
    number_returned: int
    total_matches: int
    update_id: int | None
    raw_didl: str


class MediaServer:
    """
    A discovered DLNA media server.
    A profile selected from its device description interprets family-specific behavior.
    """

    def __init__(self, description: DeviceDescription, *, http_session: aiohttp.ClientSession, timeout: float) -> None:
        """
        Configure the device description and HTTP session.

        Args:
            description (DeviceDescription): Media server device description
            http_session (aiohttp.ClientSession): HTTP session shared with DLNAClient
            timeout (float): Response timeout in seconds
        """

        self.description = description
        self.profile: Profile = select_profile(description)
        self._http_session = http_session
        self._timeout = timeout

    @property
    def content_directory(self) -> ServiceInfo:
        """Return the ContentDirectory service that provides recording listings."""

        service = self.description.find_service(_CONTENT_DIRECTORY)
        if service is None:
            raise DLNAError(f'{self.description.friendly_name} does not provide a ContentDirectory service.')
        return service

    async def browse(self, object_id: str = '0', *, start: int = 0, count: int = 0) -> BrowseResult:
        """
        Fetch a page of a folder's immediate children.

        Args:
            object_id (str): Folder ID (`0` for root)
            start (int): Starting index
            count (int): Number to fetch (0 uses the device limit)

        Returns:
            BrowseResult: Retrieved entries and total count
        """

        result = await self._call_content_directory(
            'Browse',
            {
                'ObjectID': object_id,
                'BrowseFlag': 'BrowseDirectChildren',
                'Filter': '*',
                'StartingIndex': str(start),
                'RequestedCount': str(count),
                'SortCriteria': '',
            },
        )
        return self._browse_result(result)

    async def browse_all(self, object_id: str = '0') -> list[Container | Recording]:
        """
        Fetch all pages of a folder's immediate children.

        Args:
            object_id (str): Folder ID (`0` for root)

        Returns:
            list[Container | Recording]: Folders and recordings
        """

        objects: list[Container | Recording] = []
        while True:
            result = await self.browse(object_id, start=len(objects), count=_BROWSE_PAGE_SIZE)
            objects.extend(result.objects)

            # Devices may return fewer entries than requested, so advance by the actual count
            if result.number_returned == 0 or len(objects) >= result.total_matches:
                break
        return objects

    async def get_metadata(self, object_id: str) -> Container | Recording:
        """
        Fetch one folder or recording by ID.

        Args:
            object_id (str): Folder or recording ID

        Returns:
            Container | Recording: Retrieved item
        """

        browse_result = await self.browse_metadata(object_id)
        if len(browse_result.objects) != 1:
            raise DLNAError(f'Could not retrieve the item with ID {object_id}.')
        return browse_result.objects[0]

    async def browse_metadata(self, object_id: str) -> BrowseResult:
        """
        Fetch a BrowseMetadata response by ID.
        Use this to retain the response's DIDL-Lite exactly as returned by the device.

        Args:
            object_id (str): Folder or recording ID

        Returns:
            BrowseResult: Retrieved item and response DIDL-Lite
        """

        result = await self._call_content_directory(
            'Browse',
            {
                'ObjectID': object_id,
                'BrowseFlag': 'BrowseMetadata',
                'Filter': '*',
                'StartingIndex': '0',
                'RequestedCount': '0',
                'SortCriteria': '',
            },
        )
        return self._browse_result(result)

    def interpret_http_error(self, error: DLNAError, url: str) -> DLNAError:
        """
        Interpret a media or listing HTTP error according to the recorder family.

        Args:
            error (DLNAError): Exception containing an HTTP status
            url (str): Failed request URL

        Returns:
            DLNAError: Family-specific exception, or the original if no interpretation applies
        """

        if error.http_status is None:
            return error
        interpreted = self.profile.resolve_http_status()(error.http_status, url)
        if isinstance(interpreted, DLNAError):
            return interpreted
        return error

    async def _call_content_directory(self, action: str, arguments: dict[str, str]) -> SOAPResult:
        """
        Invoke a ContentDirectory action and interpret device-specific HTTP errors.

        Args:
            action (str): Action name
            arguments (dict[str, str]): Input argument names and values

        Returns:
            SOAPResult: Action response and output arguments
        """

        service = self.content_directory
        try:
            return await call_action(
                self._http_session, service.control_url, service.service_type, action, arguments, timeout=self._timeout
            )
        except DLNAError as ex:
            raise self.interpret_http_error(ex, service.control_url) from ex

    def _browse_result(self, result: SOAPResult) -> BrowseResult:
        """
        Convert a Browse response into parsed objects and pagination metadata.

        Args:
            result (SOAPResult): ContentDirectory Browse response

        Returns:
            BrowseResult: Parsed objects and original DIDL-Lite
        """

        raw_didl = result.arguments.get('Result', '')
        number_returned = result.arguments.get('NumberReturned', '0')
        total_matches = result.arguments.get('TotalMatches', '0')
        update_id = result.arguments.get('UpdateID')
        objects = parse_didl(raw_didl, self.profile) if raw_didl != '' else []
        return BrowseResult(
            objects=tuple(objects),
            number_returned=int(number_returned) if number_returned.isdecimal() else len(objects),
            total_matches=int(total_matches) if total_matches.isdecimal() else len(objects),
            update_id=int(update_id) if update_id is not None and update_id.isdecimal() else None,
            raw_didl=raw_didl,
        )


class DLNAClient:
    """Discover DLNA media servers on the home network and create MediaServer instances."""

    def __init__(self, *, timeout: float = 10.0, http_session: aiohttp.ClientSession | None = None) -> None:
        """
        Configure communication.

        Args:
            timeout (float): Device response timeout in seconds
            http_session (aiohttp.ClientSession | None): Shared HTTP session (created by this client if None)
        """

        self._timeout = timeout
        self._http_session = http_session
        self._owns_http_session = http_session is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the HTTP session created by this client."""

        if self._owns_http_session is True and self._http_session is not None:
            await self._http_session.close()
            self._http_session = None

    async def discover(self, *, timeout: float = 3.0, interface: str | None = None, port: int = 0) -> list[MediaServer]:
        """
        Discover media servers using SSDP and return those whose descriptions were retrieved.

        Args:
            timeout (float): Seconds to wait for discovery responses
            interface (str | None): Local IPv4 address for discovery (None searches every IPv4 network)
            port (int): UDP response port (0 lets the OS choose)

        Returns:
            list[MediaServer]: Discovered media servers
        """

        responses = await search(MEDIA_SERVER_DEVICE_TYPE, timeout=timeout, interface=interface, port=port)

        # Fetch descriptions concurrently and log and exclude devices that fail
        results = await asyncio.gather(
            *(self.get_server(response.location) for response in responses), return_exceptions=True
        )
        servers: list[MediaServer] = []
        seen_udns: set[str] = set()
        for response, result in zip(responses, results, strict=True):
            if isinstance(result, BaseException):
                if isinstance(result, DLNAError) is False:
                    raise result
                _LOGGER.warning(f'Could not fetch device description: {response.location}', exc_info=result)
                continue
            # A multi-homed server may advertise a different URL on each network
            ## Deduplicate after fetching so an unreachable URL cannot hide a reachable one
            udn = result.description.udn
            if udn and udn in seen_udns:
                continue
            seen_udns.add(udn)
            servers.append(result)
        return servers

    async def get_server(self, location: str) -> MediaServer:
        """
        Create a media server from its device description URL.

        Args:
            location (str): Device description URL (SSDP LOCATION)

        Returns:
            MediaServer: Media server
        """

        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        try:
            async with self._http_session.get(location, timeout=aiohttp.ClientTimeout(total=self._timeout)) as response:
                if response.status >= 400:
                    raise DLNAError(
                        f'Could not fetch device description (HTTP {response.status}): {location}',
                        http_status=response.status,
                    )
                raw_xml = await response.text(encoding='utf-8', errors='replace')
        except (aiohttp.ClientError, TimeoutError) as ex:
            raise DLNAError(f'Could not fetch device description ({ex}): {location}') from ex
        return MediaServer(
            parse_device_description(location, raw_xml), http_session=self._http_session, timeout=self._timeout
        )
