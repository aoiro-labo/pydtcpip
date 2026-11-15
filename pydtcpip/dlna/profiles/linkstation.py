"""Buffalo LinkStation media servers."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import ChapterField, CopyCountField, Profile
from pydtcpip.dlna.profiles.generic import GENERIC


def _matches(description: DeviceDescription) -> bool:
    """
    Identify LinkStation models separately from Buffalo nasne.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the device advertises a LinkStation name
    """

    model = description.model_name.upper()
    name = description.friendly_name.upper()
    return 'LINKSTATION' in model or (
        'BUFFALO' in description.manufacturer.upper()
        and 'NASNE' not in model
        and ('LINKSTATION' in name or '[LS4' in name)
    )


LINKSTATION = Profile(
    name='linkstation',
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
