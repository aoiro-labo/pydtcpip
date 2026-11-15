"""RECBOX storage servers retaining the originating recorder's metadata."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import ChapterField, CopyCountField, Profile
from pydtcpip.dlna.profiles.generic import GENERIC


def _matches(description: DeviceDescription) -> bool:
    """
    Identify a RECBOX by its model or advertised name.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the device identifies itself as RECBOX
    """

    return 'RECBOX' in description.model_name.upper() or (
        'I-O DATA' in description.manufacturer.upper() and 'RECBOX' in description.friendly_name.upper()
    )


RECBOX = Profile(
    name='recbox',
    parent=GENERIC,
    matches=_matches,
    is_unverified=True,
    copy_count_fields=(
        CopyCountField('{urn:schemas-sony-com:av}COGCount', includes_final_move=True),
        CopyCountField('{urn:schemas-toshiba-co-jp:regzadata-1-0/}copycount', includes_final_move=True),
        CopyCountField('{urn:schemas-toshiba-co-jp:regzadata-1-0}copycount', includes_final_move=True),
        CopyCountField('{urn:schemas-sharp-co-jp:shp}ccnum', includes_final_move=True, unlimited_values=('0xff',)),
        CopyCountField(
            '{urn:schemas-panasonic-com:pxn}CopyCount',
            on_resource=True,
            includes_final_move=True,
            unlimited_values=('cf', '-1'),
        ),
    ),
    chapter_fields=(
        ChapterField('{urn:schemas-sony-com:av}chapterInfo', 'sony'),
        ChapterField('{urn:schemas-sharp-co-jp:shp}chapterList', 'sharp'),
        ChapterField('{urn:schemas-panasonic-com:pxn}ChapterList', 'panasonic', on_resource=True),
    ),
)
