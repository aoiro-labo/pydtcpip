"""Service actions and arguments advertised in UPnP service descriptions."""

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict

from pydtcpip.dlna.description import ServiceInfo
from pydtcpip.errors import DLNAError


_NAMESPACE = 'urn:schemas-upnp-org:service-1-0'


class ServiceArgument(BaseModel):
    """An action argument in the order advertised by the service."""

    model_config = ConfigDict(frozen=True)

    name: str
    direction: str
    related_state_variable: str | None


class ServiceDescription(BaseModel):
    """Successfully retrieved service capabilities and their original XML."""

    model_config = ConfigDict(frozen=True)

    service: ServiceInfo
    actions: dict[str, tuple[ServiceArgument, ...]]
    raw_xml: str
    observed_at: datetime


def parse_service_description(service: ServiceInfo, raw_xml: str) -> ServiceDescription:
    """
    Parse the action list without inferring unadvertised capabilities.

    Args:
        service (ServiceInfo): Service whose description was retrieved
        raw_xml (str): SCPD response XML

    Returns:
        ServiceDescription: Advertised actions with ordered arguments
    """

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as ex:
        raise DLNAError('Could not parse the service description XML.') from ex
    if root.tag != f'{{{_NAMESPACE}}}scpd':
        raise DLNAError('The service description has no UPnP scpd root.')
    actions: dict[str, tuple[ServiceArgument, ...]] = {}
    for action in root.iterfind(f'{{{_NAMESPACE}}}actionList/{{{_NAMESPACE}}}action'):
        name = action.findtext(f'{{{_NAMESPACE}}}name')
        if name is None:
            raise DLNAError('The service description contains an action without a name.')
        arguments: list[ServiceArgument] = []
        for argument in action.iterfind(f'{{{_NAMESPACE}}}argumentList/{{{_NAMESPACE}}}argument'):
            arguments.append(
                ServiceArgument(
                    name=argument.findtext(f'{{{_NAMESPACE}}}name') or '',
                    direction=argument.findtext(f'{{{_NAMESPACE}}}direction') or '',
                    related_state_variable=argument.findtext(f'{{{_NAMESPACE}}}relatedStateVariable'),
                )
            )
        actions[name] = tuple(arguments)
    return ServiceDescription(service=service, actions=actions, raw_xml=raw_xml, observed_at=datetime.now(UTC))
