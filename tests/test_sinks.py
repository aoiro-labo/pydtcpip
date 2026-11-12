"""Verify how FileSink handles partial data."""

from pathlib import Path

import pytest

from pydtcpip.sinks import FileSink


@pytest.mark.anyio
async def test_discard_keeps_pending_file_created_by_another_transfer(tmp_path: Path) -> None:
    """
    Deleting another Move's `.part` while it awaits finalization would lose a recording
    whose source copy count may already have been consumed.
    """

    pending_path = tmp_path / '.recording.m2ts.part'
    pending_path.write_bytes(b'resume pending')
    sink = FileSink(tmp_path / 'recording.m2ts')

    with pytest.raises(FileExistsError):
        await sink.write(b'new data')
    await sink.discard()

    assert pending_path.read_bytes() == b'resume pending'


@pytest.mark.anyio
async def test_commit_keeps_existing_file_and_pending_data(tmp_path: Path) -> None:
    """If commit fails, preserve the destination and received data, and report the latter's location."""

    path = tmp_path / 'recording.m2ts'
    sink = FileSink(path)
    await sink.write(b'received')
    await sink.persist()
    path.write_bytes(b'created by another process')

    with pytest.raises(OSError, match='The received data remains at'):
        await sink.commit()

    assert path.read_bytes() == b'created by another process'
    assert sink.pending_path.read_bytes() == b'received'


@pytest.mark.anyio
async def test_commit_moves_pending_file(tmp_path: Path) -> None:
    """After a Move, commit places the received data at the destination without leaving `.part`."""

    path = tmp_path / 'recording.m2ts'
    sink = FileSink(path)
    await sink.write(b'received')
    await sink.persist()
    await sink.commit()

    assert path.read_bytes() == b'received'
    assert sink.pending_path.exists() is False
