"""File-based ingestion-run lock (M4).

Per WP03 T028.

The lock uses a TTL-keyed file at ``<lock_dir>/<request_id>.lock``
to prevent concurrent ingestion runs from racing on the vector
store. The TTL makes a stale lock self-heal after ``ttl_seconds``
so a crashed run doesn't permanently wedge the next one.

Design choices
--------------

We use a TTL-keyed file on the shared Chroma PVC instead of
Redis because the ingestion Job runs in a cluster with no
Redis. The TTL makes a stale lock self-heal after
``ttl_seconds``. The filename carries the run's ``request_id``
so failures surface a single ID across logs, spans, the
filesystem, and the Helm Job's stdout — AGENTS.md §6.3
(single-ID propagation).

Concurrency is approximate: two Kubernetes Jobs racing on the
same source URL can both pass the ``try_acquire`` check if the
``stat`` happens before the second ``write``. In practice the
ingestion Job runs as a Helm ``post-install`` hook so two Jobs
for the same source URL would only race on a manual re-run,
and the cost of a duplicate write is a single ``upsert`` of
identical ``chunk_id``s — which is idempotent (FR-012). The
lock is a **safety belt**, not a hard mutex.
"""
from __future__ import annotations

import time
from pathlib import Path

import structlog

_log = structlog.get_logger(__name__)


class FileLockIngestionRunLock:
    """TTL-keyed file-based ingestion-run lock.

    Attributes:
        lock_dir: Directory in which the lock file is created.
        ttl_seconds: How long a lock is considered valid. A
            stale lock (older than ``ttl_seconds``) is
            overridden by a new ``try_acquire``.
    """

    def __init__(self, *, lock_dir: Path, ttl_seconds: int = 600) -> None:
        """Initialise the lock.

        Args:
            lock_dir: Directory in which the lock file is created.
            ttl_seconds: How long a lock is considered valid.
        """
        self.lock_dir: Path = Path(lock_dir)
        self.ttl_seconds: int = ttl_seconds

    def _lock_path(self, request_id: str) -> Path:
        """Return the lock-file path for ``request_id``."""
        return self.lock_dir / f"{request_id}.lock"

    def try_acquire(self, request_id: str) -> bool:
        """Attempt to acquire the lock for ``request_id``.

        Returns:
            ``True`` if the lock was free (or stale and
            overridden). ``False`` if the lock is currently
            held by an active run.
        """
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        path = self._lock_path(request_id)
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < self.ttl_seconds:
                _log.debug(
                    "ingestion_lock.held",
                    request_id=request_id,
                    age_seconds=age,
                    ttl_seconds=self.ttl_seconds,
                )
                return False
            # Stale lock — override.
            _log.debug(
                "ingestion_lock.stale_overriding",
                request_id=request_id,
                age_seconds=age,
            )
        # Write the lock file with a small payload so the operator
        # can see the holder's identity on disk.
        path.write_text(f"request_id={request_id}\nttl={self.ttl_seconds}\n")
        return True

    def release(self, request_id: str) -> None:
        """Release the lock held by ``request_id``.

        No-op if the lock does not exist (idempotent).
        """
        path = self._lock_path(request_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def is_held(self, request_id: str) -> bool:
        """Return ``True`` if the lock is currently held."""
        path = self._lock_path(request_id)
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < self.ttl_seconds


__all__ = ["FileLockIngestionRunLock"]
