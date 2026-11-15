"""Sharp AQUOS recorder and television metadata."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import ChapterField, CopyCountField, Profile
from pydtcpip.dlna.profiles.generic import GENERIC


def _matches(description: DeviceDescription) -> bool:
    """
    Match Sharp media servers using their manufacturer declaration.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the manufacturer is Sharp
    """

    return 'SHARP' in description.manufacturer.upper()


SHARP = Profile(
    name='sharp',
    parent=GENERIC,
    matches=_matches,
    is_unverified=True,
    copy_count_fields=(
        CopyCountField(
            '{urn:schemas-sharp-co-jp:shp}ccnum',
            includes_final_move=True,
            unlimited_values=('0xff',),
        ),
    ),
    chapter_fields=(ChapterField('{urn:schemas-sharp-co-jp:shp}chapterList', 'sharp'),),
)
