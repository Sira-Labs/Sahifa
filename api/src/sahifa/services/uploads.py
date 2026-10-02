"""Deleting old upload folders (spec 008).

An upload lives in `uploads_dir/<batch>/` and belongs to the connection `upload-<batch>`
(`routers/scans.py`). A folder goes once every scan of its connection has finished more than
`upload_ttl_days` ago, or, without a connection or scan, once the folder itself is that
old. A folder whose scan is `queued` or `running` is never touched. The reports, findings and
checks stay in the database.

Only plain folders directly inside the resolved `uploads_dir` are deleted. A symlink is never
followed: a symlinked folder is refused, and a symlink inside a folder is removed as a link.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import Connection, Scan
from ..logging import get_logger
from ..settings import Settings

log = get_logger("sahifa.uploads")
UPLOAD_PREFIX = "upload-"
ACTIVE = ("queued", "running")


@dataclass(frozen=True)
class Folder:
    """What the database says about an upload folder's scans."""

    active: bool
    finished_at: datetime | None


@dataclass(frozen=True)
class Cleaned:
    folders: int
    bytes: int


def folder_size(path: Path) -> int:
    """Bytes of the regular files under `path`, without following symlinks."""
    total = 0
    for top, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            info = os.lstat(os.path.join(top, name))
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def delete_folder(root: Path, folder: Path) -> int | None:
    """Delete `folder` if it is a real directory directly inside `root`; returns the bytes
    freed, or None when the path is refused (a symlink, outside `root`, not a directory)."""
    root = root.resolve()
    target = folder if folder.is_absolute() else root / folder
    if target.is_symlink():
        log.warning("uploads.refused", folder=target.name, reason="symlink")
        return None
    real = target.resolve()
    if real.parent != root or not real.is_dir():
        log.warning("uploads.refused", folder=target.name, reason="not a folder inside the uploads folder")
        return None
    size = folder_size(real)
    try:
        # rmtree removes symlinks inside the tree as links and refuses a symlinked top.
        shutil.rmtree(real)
    except OSError as e:
        log.warning("uploads.refused", folder=real.name, reason=str(e)[:200])
        return None
    return size


async def _folders(sessions: async_sessionmaker[AsyncSession]) -> dict[str, Folder]:
    """Upload folder name -> whether a scan is active and when the last one finished."""
    async with sessions() as db:
        rows = (
            await db.execute(
                select(
                    Connection.name,
                    func.bool_or(Scan.status.in_(ACTIVE)),
                    func.max(func.coalesce(Scan.finished_at, Scan.created_at)),
                )
                .join(Scan, Scan.connection_id == Connection.id)
                .where(Connection.kind == "upload")
                .group_by(Connection.name)
            )
        ).all()
    return {
        name.removeprefix(UPLOAD_PREFIX): Folder(active=bool(active), finished_at=finished)
        for name, active, finished in rows
        if name.startswith(UPLOAD_PREFIX)
    }


def _sweep(root: Path, known: dict[str, Folder], cutoff: datetime) -> Cleaned:
    folders = freed = 0
    if not root.is_dir():
        return Cleaned(0, 0)
    for entry in os.scandir(root):
        path = Path(entry.path)
        if entry.is_symlink():
            log.warning("uploads.refused", folder=entry.name, reason="symlink")
            continue
        if not entry.is_dir(follow_symlinks=False):
            continue
        state = known.get(entry.name)
        if state is not None:
            if state.active or state.finished_at is None or state.finished_at >= cutoff:
                continue
        else:
            # An orphan: no scan refers to it (for instance an upload whose request failed).
            modified = datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime, UTC)
            if modified >= cutoff:
                continue
        size = delete_folder(root, path)
        if size is not None:
            folders += 1
            freed += size
    return Cleaned(folders, freed)


async def clean_uploads(sessions: async_sessionmaker[AsyncSession], settings: Settings) -> Cleaned:
    """Delete the upload folders older than `upload_ttl_days`."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.upload_ttl_days)
    known = await _folders(sessions)
    root = settings.uploads_dir.resolve()
    cleaned = await anyio.to_thread.run_sync(lambda: _sweep(root, known, cutoff))
    log.info("uploads.cleaned", folders=cleaned.folders, bytes=cleaned.bytes)
    return cleaned
