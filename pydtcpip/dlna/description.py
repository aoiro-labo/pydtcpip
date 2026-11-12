"""Parse UPnP device descriptions."""

from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict

from pydtcpip.errors import DLNAError


_DEVICE_NAMESPACE = 'urn:schemas-upnp-org:device-1-0'


class ServiceInfo(BaseModel):
    """A UPnP service with absolute URLs resolved against the device description location."""

    model_config = ConfigDict(frozen=True)

    service_type: str
    service_id: str
    control_url: str
    event_sub_url: str
    scpd_url: str


class DeviceDescription(BaseModel):
    """Device information parsed from a UPnP description and the complete description."""

    model_config = ConfigDict(frozen=True)

    location: str
    udn: str
    device_type: str
    friendly_name: str
    manufacturer: str
    model_name: str
    model_description: str | None
    model_number: str | None
    services: tuple[ServiceInfo, ...]
    # Element and attribute namespaces in the description, used to identify the device family
    namespaces: frozenset[str]
    # Namespaced extension elements directly under device (`{namespace}name` and value)
    extensions: dict[str, str]
    raw_xml: str

    def find_service(self, service_type_prefix: str) -> ServiceInfo | None:
        """
        Find a service by its type prefix.

        Args:
            service_type_prefix (str): Type prefix such as `urn:schemas-upnp-org:service:ContentDirectory:`

        Returns:
            ServiceInfo | None: First matching service, or None
        """

        for service in self.services:
            if service.service_type.startswith(service_type_prefix) is True:
                return service
        return None


def parse_device_description(location: str, raw_xml: str) -> DeviceDescription:
    """
    Parse a device description XML document.

    Args:
        location (str): URL of the description, used to resolve relative service URLs
        raw_xml (str): Device description XML

    Returns:
        DeviceDescription: Parsed device information
    """

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as ex:
        raise DLNAError(f'Could not parse the device description XML ({location}).') from ex
    device = root.find(f'{{{_DEVICE_NAMESPACE}}}device')
    if device is None:
        raise DLNAError(f'The device description has no device element ({location}).')

    # Resolve service URLs against URLBase when present, otherwise against the description location
    base_url = (root.findtext(f'{{{_DEVICE_NAMESPACE}}}URLBase') or '').strip() or location
    services: list[ServiceInfo] = []
    for service in device.iterfind(f'{{{_DEVICE_NAMESPACE}}}serviceList/{{{_DEVICE_NAMESPACE}}}service'):
        services.append(
            ServiceInfo(
                service_type=(service.findtext(f'{{{_DEVICE_NAMESPACE}}}serviceType') or '').strip(),
                service_id=(service.findtext(f'{{{_DEVICE_NAMESPACE}}}serviceId') or '').strip(),
                control_url=urljoin(base_url, (service.findtext(f'{{{_DEVICE_NAMESPACE}}}controlURL') or '').strip()),
                event_sub_url=urljoin(
                    base_url, (service.findtext(f'{{{_DEVICE_NAMESPACE}}}eventSubURL') or '').strip()
                ),
                scpd_url=urljoin(base_url, (service.findtext(f'{{{_DEVICE_NAMESPACE}}}SCPDURL') or '').strip()),
            )
        )

    # Collect namespaces throughout the description and extension elements directly under device
    namespaces: set[str] = set()
    for element in root.iter():
        if element.tag.startswith('{') is True:
            namespaces.add(element.tag[1:].partition('}')[0])
        for attribute_name in element.attrib:
            if attribute_name.startswith('{') is True:
                namespaces.add(attribute_name[1:].partition('}')[0])
    extensions: dict[str, str] = {}
    for child in device:
        if child.tag.startswith(f'{{{_DEVICE_NAMESPACE}}}') is False:
            extensions[child.tag] = (child.text or '').strip()

    def text_of(name: str) -> str | None:
        value = device.findtext(f'{{{_DEVICE_NAMESPACE}}}{name}')
        if value is None:
            return None
        return value.strip()

    return DeviceDescription(
        location=location,
        udn=text_of('UDN') or '',
        device_type=text_of('deviceType') or '',
        friendly_name=text_of('friendlyName') or '',
        manufacturer=text_of('manufacturer') or '',
        model_name=text_of('modelName') or '',
        model_description=text_of('modelDescription'),
        model_number=text_of('modelNumber'),
        services=tuple(services),
        namespaces=frozenset(namespaces),
        extensions=extensions,
        raw_xml=raw_xml,
    )
