"""Parse DLNA protocolInfo and DTCP-IP Content-Type parameters."""

from pydtcpip.models import ProtocolInfo


def parse_content_type(value: str) -> tuple[str, dict[str, str]]:
    """
    Split Content-Type into a MIME type and parameters.
    For example: `application/x-dtcp1;DTCP1HOST=192.0.2.1;DTCP1PORT=5000;CONTENTFORMAT=video/mpeg`.

    Args:
        value (str): Content-Type value (also the format of the third protocolInfo field)

    Returns:
        tuple[str, dict[str, str]]: Lowercase MIME type and parameter names and values
    """

    content_type, *parts = value.split(';')
    parameters: dict[str, str] = {}
    for part in parts:
        name, separator, parameter_value = part.partition('=')
        if separator == '':
            continue
        # CONTENTFORMAT values can be quoted
        parameters[name.strip()] = parameter_value.strip().strip('"')
    return content_type.strip().lower(), parameters


def parse_protocol_info(value: str) -> ProtocolInfo:
    """
    Parse a resource's protocolInfo (`<protocol>:<network>:<MIME type>:<additional info>`).

    Args:
        value (str): res@protocolInfo value

    Returns:
        ProtocolInfo: Parsed protocolInfo (partially populated if malformed)
    """

    # MIME type parameters contain no colons, so split at the first three colons
    fields = value.split(':', 3)
    while len(fields) < 4:
        fields.append('')
    protocol, network, content_type_field, additional = fields
    content_type, content_type_parameters = parse_content_type(content_type_field)

    # Additional information consists of semicolon-separated `name=value` pairs (`*` means none)
    parameters: dict[str, str] = {}
    for part in additional.split(';'):
        name, separator, parameter_value = part.partition('=')
        if separator == '':
            continue
        parameters[name.strip()] = parameter_value.strip()

    return ProtocolInfo(
        raw=value,
        protocol=protocol,
        network=network,
        content_type=content_type,
        parameters=parameters,
        content_type_parameters=content_type_parameters,
    )
