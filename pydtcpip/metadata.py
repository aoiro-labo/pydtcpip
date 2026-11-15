"""Persist recording metadata separately from media bytes and Move resume secrets."""

import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Self

from pydtcpip.events import TransferEvent
from pydtcpip.models import RecordingMetadata


_LOGGER = logging.getLogger(__name__)


class MetadataSidecar:
    """The existing program XML and an extensible JSON archive beside a received recording."""

    def __init__(self, output: Path, metadata: RecordingMetadata) -> None:
        """
        Create and persist both metadata files before the source copy can be consumed.

        Args:
            output (Path): Media destination whose suffix determines the sidecar names
            metadata (RecordingMetadata): Collected metadata, responses and query statuses
        """

        self.path = output.with_suffix('.metadata.json')
        self.metadata = metadata
        xml_path = output.with_suffix('.xml')
        if xml_path.exists() or self.path.exists():
            raise FileExistsError(f'Recording metadata already exists beside {output}.')
        # Preserve the established readable XML format; the JSON also retains the pre-normalization input
        with xml_path.open('x', encoding='utf-8') as file:
            file.write(metadata.recording.raw_xml)
            file.flush()
            os.fsync(file.fileno())
        with self.path.open('x', encoding='utf-8') as file:
            file.write(metadata.model_dump_json(indent=2))
            file.flush()
            os.fsync(file.fileno())

    @classmethod
    def resume(cls, output: Path) -> Self | None:
        """
        Reopen the metadata archive when resuming a previously received recording.

        Args:
            output (Path): Media destination

        Returns:
            Self | None: Existing archive, or None for transfers created without a JSON sidecar
        """

        path = output.with_suffix('.metadata.json')
        if path.exists() is False:
            return None
        instance = cls.__new__(cls)
        instance.path = path
        instance.metadata = RecordingMetadata.model_validate_json(path.read_bytes())
        return instance

    def on_event(self, event: TransferEvent) -> None:
        """
        Retain transfer metadata and lifecycle events without authentication or resume secrets.
        Log I/O failures and keep events in memory for the next update while the transfer continues.

        Args:
            event (TransferEvent): Event associated with this recording
        """

        if event.type not in (
            'media_info_received',
            'transfer_started',
            'transfer_protection_observed',
            'transfer_received',
            'sink_persisted',
            'move_finalize_requested',
            'move_finalized',
            'move_completed',
            'move_cancel_requested',
            'move_cancelled',
            'move_resume_required',
            'move_finalize_rejected',
        ):
            return
        self.metadata = self.metadata.model_copy(
            update={
                'transfer_events': (*self.metadata.transfer_events, event.model_dump(mode='json')),
            }
        )
        # Replace only our JSON archive so interruption while recording an event preserves the previous snapshot
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, delete=False) as file:
                pending_path = Path(file.name)
                try:
                    file.write(self.metadata.model_dump_json(indent=2))
                    file.flush()
                    os.fsync(file.fileno())
                except BaseException:
                    file.close()
                    pending_path.unlink(missing_ok=True)
                    raise
            try:
                os.replace(pending_path, self.path)
            finally:
                pending_path.unlink(missing_ok=True)
        except OSError as ex:
            # FINALIZE may already have consumed a copy; continue committing the media and saving resume state
            _LOGGER.warning(
                f'Could not update recording metadata at {self.path}; transfer processing will continue.',
                exc_info=ex,
            )
