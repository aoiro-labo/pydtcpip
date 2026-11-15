"""Read-only nasne recording metadata and chapter endpoints."""

import re
from itertools import pairwise
from urllib.parse import urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from pydtcpip.dlna.extensions.base import MetadataExtension
from pydtcpip.errors import DLNAError
from pydtcpip.models import Chapter, ChapterList, MetadataQuery, MetadataResponse, Recording


class NasneTitleList(BaseModel):
    """A page of nasne's recording details with unmodified JSON field names and values."""

    model_config = ConfigDict(frozen=True)

    errorcode: int
    totalMatches: int
    numberReturned: int
    item: tuple[dict[str, JsonValue], ...]


class NasneTitleListResult(BaseModel):
    """Parsed nasne details and the complete HTTP response."""

    model_config = ConfigDict(frozen=True)

    titles: NasneTitleList
    response: MetadataResponse


class NasneExtension(MetadataExtension):
    """Additional metadata queries that share the DLNA client's session."""

    def _title_id(self, recording: Recording) -> str:
        """
        Extract the numeric title identifier without changing the recording's DIDL ID.

        Args:
            recording (Recording): Recording returned by ContentDirectory

        Returns:
            str: Identifier accepted by the nasne metadata API
        """

        identifier = recording.reference_id or recording.id
        match = re.search(r'(?:^|[?&])id=(\d+)(?:&|$)', identifier)
        if match is not None:
            return match.group(1)
        if identifier.isdecimal() is True:
            return identifier
        raise DLNAError('The recording ID does not contain a nasne numeric title ID.')

    async def get_details(self, recording: Recording) -> tuple[MetadataQuery, ...]:
        """
        Find a recording in the paginated detail list, preserving the matching response.

        Args:
            recording (Recording): Recording selected through ContentDirectory

        Returns:
            tuple[MetadataQuery, ...]: Matching details or an omitted status
        """

        identifier = self._title_id(recording)
        start = 0
        while True:
            result = await self.get_title_list(start=start)
            for item in result.titles.item:
                if str(item.get('id')) == identifier:
                    return (
                        MetadataQuery(
                            name='recording_details',
                            status='known',
                            data={
                                'recording': item,
                                'response': result.response.model_dump(mode='json'),
                            },
                        ),
                    )
            start += result.titles.numberReturned
            if result.titles.numberReturned == 0 or start >= result.titles.totalMatches:
                return (MetadataQuery(name='recording_details', status='omitted'),)

    def _url(self, port: int, action: str, parameters: dict[str, str]) -> str:
        """
        Resolve a nasne API endpoint on the discovered server.

        Args:
            port (int): Endpoint port
            action (str): Read-only endpoint name
            parameters (dict[str, str]): Query parameters

        Returns:
            str: Absolute metadata URL
        """

        location = urlsplit(self.server.description.location)
        host = location.hostname
        if host is None:
            raise DLNAError('The device description URL has no hostname.')
        if ':' in host:
            host = f'[{host}]'
        return urlunsplit((location.scheme, f'{host}:{port}', f'/recorded/{action}', urlencode(parameters), ''))

    async def get_title_list(
        self,
        *,
        start: int = 0,
        count: int = 100,
        search_criteria: int = 0,
        with_long_description: bool = True,
        with_user_data: bool = False,
    ) -> NasneTitleListResult:
        """
        Fetch a page of recording details without modifying playback or protection state.

        Args:
            start (int): Starting index
            count (int): Requested item count
            search_criteria (int): Device-specific search criterion (0 for the normal recording list)
            with_long_description (bool): Include extended program descriptions
            with_user_data (bool): Include user-specific recording metadata

        Returns:
            NasneTitleListResult: Details and the original response
        """

        response = await self.server.fetch_metadata(
            self._url(
                64220,
                'titleListGet',
                {
                    'searchCriteria': str(search_criteria),
                    'filter': '0',
                    'startingIndex': str(start),
                    'requestedCount': str(count),
                    'sortCriteria': '0',
                    'withDescriptionLong': str(int(with_long_description)),
                    'withUserData': str(int(with_user_data)),
                },
            )
        )
        try:
            titles = NasneTitleList.model_validate_json(response.body)
        except ValidationError as ex:
            raise DLNAError('The nasne recording list has an invalid JSON structure.') from ex
        if titles.errorcode != 0:
            raise DLNAError(f'nasne rejected the recording-list request (error {titles.errorcode}).')
        return NasneTitleListResult(titles=titles, response=response)

    async def get_chapters(self, recording: Recording) -> ChapterList:
        """
        Retrieve binary chapter positions and estimate their times from the thumbnail map.

        Args:
            recording (Recording): Recording with its original DIDL ID

        Returns:
            ChapterList: Original positions and estimated milliseconds, retaining unmappable points
        """

        identifier = self._title_id(recording)
        mapping = await self.server.fetch_metadata(self._url(64210, 'thumbnailMapGet', {'id': identifier}))
        chapter_response = await self.server.fetch_metadata(
            self._url(
                64220,
                'recordedContentChpDataGet',
                {
                    'id': identifier,
                    'offset': '0',
                    'length': '0',
                },
            )
        )
        if len(mapping.body) < 4:
            raise DLNAError('The nasne thumbnail map is truncated.')
        count = int.from_bytes(mapping.body[:4], 'big')
        if len(mapping.body) != 4 + count * 4:
            raise DLNAError('The nasne thumbnail-map size does not match its entry count.')
        if len(chapter_response.body) % 16 != 0:
            raise DLNAError('The nasne chapter response contains a truncated record.')
        positions = [
            int.from_bytes(mapping.body[offset + 1 : offset + 4], 'big') for offset in range(4, len(mapping.body), 4)
        ]
        chapters: list[Chapter] = []
        for offset in range(0, len(chapter_response.body), 16):
            position = int.from_bytes(chapter_response.body[offset : offset + 8], 'little') >> 11
            milliseconds: int | None = None
            for index, (start, end) in enumerate(pairwise(positions)):
                if start <= position < end:
                    milliseconds = index * 15000 + (position - start) * 15000 // (end - start)
                    break
            chapters.append(
                Chapter(
                    position_ms=milliseconds,
                    source_position=position,
                    is_estimated=milliseconds is not None,
                )
            )
        return ChapterList(
            status='known',
            chapters=tuple(chapters),
            sources=(mapping.url, chapter_response.url),
            raw_responses=(mapping.body, chapter_response.body),
            observed_at=chapter_response.observed_at,
        )

    async def get_thumbnail(self, title_id: str, entry_id: int) -> MetadataResponse:
        """
        Fetch a thumbnail entry without changing the recording's resume position.

        Args:
            title_id (str): Numeric title ID from the recording list
            entry_id (int): Zero-based entry in the thumbnail map

        Returns:
            MetadataResponse: Original thumbnail response
        """

        return await self.server.fetch_metadata(
            self._url(
                64210,
                'recordedContentThumbnailGet',
                {
                    'id': title_id,
                    'thumbnailEntryId': str(entry_id),
                },
            )
        )
