"""Profiles describing device-family behavior."""

from collections.abc import Callable
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from pydtcpip.dlna.description import DeviceDescription
from pydtcpip.errors import PyDTCPIPError
from pydtcpip.models import ProtectionValue


@dataclass(frozen=True)
class Profile:
    """
    Device-family behavior, organized in a tree rooted at generic DLNA.
    Child profiles define only differences from their parents; None values are resolved through the parent chain.
    The root defines standard DLNA behavior. Profiles are stateless and contain only settings and functions
    that take raw data and return values.
    """

    # Family name (matching the filename)
    name: str
    # Parent profile (None only for the generic root)
    parent: 'Profile | None'
    # Match a device description (only devices matching the parent are eligible)
    matches: Callable[[DeviceDescription], bool] | None = None
    # Read remaining copies from a recording's DIDL-Lite item
    read_remaining_copy_count: Callable[[ET.Element], ProtectionValue[int]] | None = None
    # Interpret an HTTP status as a family-specific exception (or return None)
    interpret_http_status: Callable[[int, str], PyDTCPIPError | None] | None = None
    # Whether BrowseDirectChildren includes fields absent from BrowseMetadata
    has_listing_only_metadata: bool | None = None

    @property
    def depth(self) -> int:
        """Return the depth from the generic root (zero for the root)."""

        depth = 0
        profile = self.parent
        while profile is not None:
            depth += 1
            profile = profile.parent
        return depth

    def is_match(self, description: DeviceDescription) -> bool:
        """
        Return whether the device matches this profile and all its ancestors.

        Args:
            description (DeviceDescription): Recorder device description

        Returns:
            bool: True if the device matches this family
        """

        profile: Profile | None = self
        while profile is not None:
            if profile.matches is not None and profile.matches(description) is False:
                return False
            profile = profile.parent
        return True

    def resolve_remaining_copy_count(self) -> Callable[[ET.Element], ProtectionValue[int]]:
        """
        Resolve the copy count reader through the parent chain.

        Returns:
            Callable[[ET.Element], ProtectionValue[int]]: Function defined by the nearest ancestor
        """

        profile: Profile | None = self
        while profile is not None:
            if profile.read_remaining_copy_count is not None:
                return profile.read_remaining_copy_count
            profile = profile.parent
        raise LookupError('The generic root profile has no read_remaining_copy_count function.')

    def resolve_http_status(self) -> Callable[[int, str], PyDTCPIPError | None]:
        """
        Resolve the HTTP status interpreter through the parent chain.

        Returns:
            Callable[[int, str], PyDTCPIPError | None]: Function defined by the nearest ancestor
        """

        profile: Profile | None = self
        while profile is not None:
            if profile.interpret_http_status is not None:
                return profile.interpret_http_status
            profile = profile.parent
        raise LookupError('The generic root profile has no interpret_http_status function.')

    def resolve_has_listing_only_metadata(self) -> bool:
        """
        Resolve whether listings contain fields absent from individual recording metadata.

        Returns:
            bool: Value defined by the nearest ancestor
        """

        profile: Profile | None = self
        while profile is not None:
            if profile.has_listing_only_metadata is not None:
                return profile.has_listing_only_metadata
            profile = profile.parent
        raise LookupError('The generic root profile has no has_listing_only_metadata value.')
