"""Sony BDZ recorder metadata and optional service extensions."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import ChapterField, CopyCountField, Profile
from pydtcpip.dlna.profiles.generic import GENERIC


def _matches(description: DeviceDescription) -> bool:
    """
    Identify BDZ recorders without including Sony's other media servers.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether the device advertises a BDZ model
    """

    model = description.model_name.upper()
    return 'SONY' in description.manufacturer.upper() and (model == 'SONY-BDZ' or model.startswith('BDZ-'))


SONY_BDZ = Profile(
    name='sony_bdz',
    parent=GENERIC,
    matches=_matches,
    is_unverified=True,
    copy_count_fields=(CopyCountField('{urn:schemas-sony-com:av}COGCount', includes_final_move=True),),
    chapter_fields=(ChapterField('{urn:schemas-sony-com:av}chapterInfo', 'sony'),),
    extension='sony',
)
