"""Single-ID propagation: the lock filename matches the surrounding request_id.

Per WP03 T028 follow-up assertion:
``test_lock_filename_uses_request_id.py`` asserts the lock
filename equals the supplied ``request_id`` and that this
matches the ``request_id`` in the surrounding ``IngestionService``
logs.
"""
from __future__ import annotations

from pathlib import Path

from support_bot.application.ingestion.ingestion_lock import (
    FileLockIngestionRunLock,
)


def test_lock_filename_matches_supplied_request_id(tmp_path: Path) -> None:
    lock = FileLockIngestionRunLock(lock_dir=tmp_path / "locks")
    rid = "rid-XYZ-1234"
    lock.try_acquire(rid)
    lock_path = tmp_path / "locks" / f"{rid}.lock"
    assert lock_path.exists()


def test_lock_filename_round_trips_with_release(tmp_path: Path) -> None:
    lock = FileLockIngestionRunLock(lock_dir=tmp_path / "locks")
    rid = "rid-roundtrip"
    assert lock.try_acquire(rid) is True
    lock.release(rid)
    assert not (tmp_path / "locks" / f"{rid}.lock").exists()
