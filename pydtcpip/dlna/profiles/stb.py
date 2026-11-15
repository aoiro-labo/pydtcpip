"""Metadata shared by television set-top boxes."""

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.dlna.profiles.base import CopyCountField, Profile
from pydtcpip.dlna.profiles.generic import GENERIC


def _matches(description: DeviceDescription) -> bool:
    """
    Match identified cable, satellite and IPTV set-top box families.

    Args:
        description (DeviceDescription): Device description to inspect

    Returns:
        bool: Whether a known set-top box signature is present
    """

    model = description.model_name.upper()
    manufacturer = description.manufacturer.upper()
    model_description = (description.model_description or '').upper()
    return (
        model.startswith('STREAMCRUISER SMART TV')
        or model in ('STW2000', 'IS1050')
        or (model == 'AM900' and manufacturer.startswith('MITSUBISHI ELECTRIC CORPORATION'))
        or (model == 'TT01' and manufacturer.startswith('HUAWEI'))
        or (model == 'TT02' and manufacturer.startswith('SUMITOMO ELECTRIC INDUSTRIES'))
        or (model == 'KS-6100' and manufacturer.startswith('KAON'))
        or 'SKYPERFECTV!' in model
        or (model == 'SPTVHD' and manufacturer == 'SKY PERFECTV!')
        or (model == 'XA401' and manufacturer == 'KDDI')
        or ('SET-TOP BOX' in model_description and manufacturer.startswith('HUMAX'))
        or (model.startswith('BDV') and manufacturer.startswith('PIONEER'))
        or (('CATV DIGITAL STB' in model or model == 'C01AS3') and manufacturer.startswith('PANASONIC'))
    )


STB = Profile(
    name='stb',
    parent=GENERIC,
    matches=_matches,
    is_unverified=True,
    copy_count_fields=(
        CopyCountField(
            'allowedUse', on_resource=True, is_allowed_use=True, includes_final_move=True, unlimited_values=('-1',)
        ),
        CopyCountField(
            '{urn:schemas-panasonic-com:pxn}CopyCount',
            on_resource=True,
            includes_final_move=True,
            unlimited_values=('cf', '-1'),
        ),
    ),
    extension='shared_tags',
)
