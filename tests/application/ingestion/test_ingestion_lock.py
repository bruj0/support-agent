"""TDD red tests for ``application.ingestion.ingestion_lock.FileLockIngestionRunLock``.

Per WP03 T028.

The lock uses a TTL-keyed file at ``<lock_dir>/<request_id>.lock``
to prevent concurrent ingestion runs (M4). The TTL makes a stale
lock self-heal after ``ttl_seconds``.

The filename carries the run's ``request_id`` so failures
surface a single ID across logs, spans, the filesystem, and the
Helm Job's stdout — AGENTS.md §6.3.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from support_bot.application.ingestion.ingestion_lock import (
    FileLockIngestionRunLock,
)


@pytest.fixture
def lock_dir(tmp_path: Path) -> Path:
    return tmp_path / "locks"


def test_try_acquire_returns_true_when_free(lock_dir: Path) -> None:
    """First acquire returns True; lock file is created."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-1") is True
    assert (lock_dir / "rid-1.lock").exists()


def test_try_acquire_returns_false_when_held(lock_dir: Path) -> None:
    """A second acquire with the same id returns False."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-1") is True
    assert lock.try_acquire("rid-1") is False


def test_try_acquire_with_different_ids_both_succeed(lock_dir: Path) -> None:
    """Different request_ids can be acquired in parallel."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-1") is True
    assert lock.try_acquire("rid-2") is True


def test_release_removes_lock_file(lock_dir: Path) -> None:
    """``release`` deletes the lock file so a future acquire succeeds."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-1") is True
    lock.release("rid-1")
    assert not (lock_dir / "rid-1.lock").exists()
    assert lock.try_acquire("rid-1") is True


def test_release_is_idempotent(lock_dir: Path) -> None:
    """``release`` on a non-existent lock is a no-op (no raise)."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    lock.release("never-acquired")  # no raise


def test_try_acquire_after_ttl_expiry_succeeds(
    lock_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the TTL elapses, a stale lock is overridden by a new acquire."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir, ttl_seconds=10)
    assert lock.try_acquire("rid-1") is True
    # Move the file mtime into the past beyond the TTL.
    lock_file = lock_dir / "rid-1.lock"
    stale = time.time() - 100
    import os

    os.utime(lock_file, (stale, stale))
    # A new acquire should succeed (stale lock overridden).
    assert lock.try_acquire("rid-1") is True


def test_is_held_returns_true_after_acquire(lock_dir: Path) -> None:
    """``is_held`` reports True while the lock is held by ``rid-1``."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-1") is True
    assert lock.is_held("rid-1") is True


def test_is_held_returns_false_after_release(lock_dir: Path) -> None:
    """``is_held`` returns False after release."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    assert lock.try_acquire("rid-1") is True
    lock.release("rid-1")
    assert lock.is_held("rid-1") is False


def test_lock_filename_uses_request_id(lock_dir: Path) -> None:
    """Lock filename is ``<request_id>.lock``."""
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    lock.try_acquire("rid-XYZ")
    assert (lock_dir / "rid-XYZ.lock").exists()


def test_try_acquire_creates_lock_dir(lock_dir: Path) -> None:
    """``try_acquire`` creates the lock directory if it does not exist."""
    assert not lock_dir.exists()
    lock = FileLockIngestionRunLock(lock_dir=lock_dir)
    lock.try_acquire("rid-1")
    assert lock_dir.is_dir()
