"""Optional metadata operations sharing a media server's connection."""

from typing import TYPE_CHECKING

from pydtcpip.models import ChapterList, MetadataQuery, Recording


if TYPE_CHECKING:
    from pydtcpip.dlna.client import MediaServer


class MetadataExtension:
    """Base interface for optional, explicitly requested device metadata."""

    # Every newly added communication path requires real-device verification
    is_unverified = True

    def __init__(self, server: 'MediaServer') -> None:
        """
        Share the media server's session and device description.

        Args:
            server (MediaServer): Server to query
        """

        self.server = server

    async def get_details(self, recording: Recording) -> tuple[MetadataQuery, ...]:
        """
        Report the absence of a family-specific detail API in the default extension.

        Args:
            recording (Recording): Recording to query

        Returns:
            tuple[MetadataQuery, ...]: Acquisition status of the optional detail query
        """

        return (MetadataQuery(name='recording_details', status='unsupported'),)

    async def get_chapters(self, recording: Recording) -> ChapterList:
        """
        Retrieve a chapter document when the recording advertises a supported reference.

        Args:
            recording (Recording): Recording whose chapter reference should be followed

        Returns:
            ChapterList: Chapter points, or an omitted status when there is no reference
        """

        # Import here to keep the parsing module independent of the extension interface
        from pydtcpip.dlna.extensions.xml_chapters import parse_chapters

        if len(recording.chapter_resources) == 0:
            return ChapterList(status='omitted')
        reference = recording.chapter_resources[0]
        response = await self.server.fetch_metadata(reference.url)
        return ChapterList(
            status='known',
            chapters=parse_chapters(response.body, reference.format),
            sources=(response.url,),
            raw_responses=(response.body,),
            observed_at=response.observed_at,
        )
