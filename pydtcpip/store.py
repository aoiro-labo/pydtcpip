"""Manage credentials and device revocation information in an application-selected data directory."""

import logging
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import typer
from pydantic_settings import BaseSettings, SettingsConfigDict

from pydtcpip.dtcp.crypto import DeviceCredentials
from pydtcpip.dtcp.srm import SRM
from pydtcpip.errors import PyDTCPIPError


_LOGGER = logging.getLogger('pydtcpip')


class _CredentialSettings(BaseSettings):
    """Credentials loaded from a dotenv file, with environment variables taking precedence."""

    model_config = SettingsConfigDict(env_prefix='PYDTCPIP_', extra='ignore', hide_input_in_errors=True)

    certificate: str = ''
    private_key: str = ''

    def __init__(self, credentials_file: Path) -> None:
        """
        Load credentials from the specified file and environment.

        Args:
            credentials_file (Path): Credentials file in dotenv format
        """

        super().__init__(_env_file=credentials_file, _env_file_encoding='utf-8')


class DeviceStore:
    """
    Store credentials and SRMs for use by the CLI and applications.
    Callers explicitly create this object and invoke its methods to load files and save SRMs.
    Users provide the credentials file; SRMs are received from peer devices.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        """
        Select the data directory for credentials and SRMs.

        Args:
            data_dir (Path | None): Destination (defaults to the OS user data directory)
        """

        if data_dir is None:
            # SRMs are updated from devices, so use the XDG data directory on Linux
            # On macOS and Windows, use Application Support and AppData respectively
            if sys.platform in ('darwin', 'win32'):
                data_dir = Path(typer.get_app_dir('pydtcpip'))
            else:
                data_dir = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'pydtcpip'
        self.data_dir = data_dir

    def load_credentials(self, path: Path | None = None) -> DeviceCredentials:
        """
        Load credentials, preferring environment variables, and verify that the certificate and key match.

        Args:
            path (Path | None): File to load (defaults to credentials.env in the data directory)

        Returns:
            DeviceCredentials: Verified credentials
        """

        # Report an invalid explicit path instead of connecting with different credentials
        if path is not None and path.is_file() is False:
            raise FileNotFoundError(f'Credentials file not found: {path}')
        credentials_file = path if path is not None else self.data_dir / 'credentials.env'
        settings = _CredentialSettings(credentials_file)
        if settings.certificate == '' or settings.private_key == '':
            raise ValueError(
                f'Place credentials in {credentials_file} or set the PYDTCPIP_CERTIFICATE '
                'and PYDTCPIP_PRIVATE_KEY environment variables.'
            )
        return DeviceCredentials(
            certificate=bytes.fromhex(settings.certificate), private_key=bytes.fromhex(settings.private_key)
        )

    def load_srm(self) -> SRM | None:
        """
        Load a saved SRM and verify its signature.

        Returns:
            SRM | None: Verified SRM (None if missing or verification failed)
        """

        path = self.data_dir / 'srm.bin'
        if path.exists() is False:
            return None
        try:
            return SRM.parse(path.read_bytes())
        except PyDTCPIPError as ex:
            _LOGGER.warning(f'Could not load the saved SRM; authenticating with version 0: {path}', exc_info=ex)
            return None

    def save_srm(self, srm: SRM) -> None:
        """
        Save a newer SRM for future authentication.
        This method can be passed directly as on_srm_update to DTCPClient or DubbingReceiver.

        Args:
            srm (SRM): Verified SRM received during authentication
        """

        path = self.data_dir / 'srm.bin'
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as file:
            os.chmod(file.name, 0o600)
            file.write(srm.data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(file.name, path)
        _LOGGER.info(f'Saved newer SRM (version {srm.version}): {path}')
