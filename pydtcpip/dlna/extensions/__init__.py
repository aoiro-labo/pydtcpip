"""Select optional communication extensions without family branches in the DLNA client."""

from typing import TYPE_CHECKING

from pydtcpip.dlna.extensions.base import MetadataExtension
from pydtcpip.dlna.extensions.nasne import NasneExtension
from pydtcpip.dlna.extensions.sony import SonyExtension
from pydtcpip.dlna.extensions.xml_chapters import SharedTagsExtension, ToshibaExtension


if TYPE_CHECKING:
    from pydtcpip.dlna.client import MediaServer


_EXTENSIONS: dict[str, type[MetadataExtension]] = {
    'nasne': NasneExtension,
    'sony': SonyExtension,
    'toshiba': ToshibaExtension,
    'shared_tags': SharedTagsExtension,
}


def create_extension(server: 'MediaServer') -> MetadataExtension:
    """
    Select the extension requested by the device-family profile.

    Args:
        server (MediaServer): Media server with a selected profile

    Returns:
        MetadataExtension: Optional metadata interface sharing the server's connection
    """

    name = server.profile.resolve_extension()
    extension_type = _EXTENSIONS.get(name, MetadataExtension) if name is not None else MetadataExtension
    return extension_type(server)


__all__ = ['MetadataExtension', 'NasneExtension', 'SonyExtension', 'create_extension']
