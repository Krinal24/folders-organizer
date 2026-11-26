"""Find items TidyByte sent to the Recycle Bin and put them back.

Nothing here deletes anything. We read the bin's own records, find the
one whose original path and deletion time match our journal entry, and
move it back, which is what "Restore" in Explorer does.

Windows: each drive has $Recycle.Bin\\<user SID>\\ holding, per item, an
$I file (original path, deletion time) and an $R file or folder with the
same suffix (the data itself).
Linux: the freedesktop.org trash, ~/.local/share/Trash/{info,files}.
macOS keeps no readable record of where an item came from, so it is not
supported; the user restores from the Trash by hand.
"""
import os
import shutil
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


# Our journal records the time right after the delete; the bin records
# its own. They should be within a second, but allow for slow disks.
MATCH_WINDOW = 120

# Seconds between 1601-01-01 (Windows FILETIME epoch) and 1970-01-01.
FILETIME_EPOCH = 11644473600


class RestoreUnsupported(Exception):
    pass


@dataclass
class Trashed:
    original: str      # The path it was deleted from.
    deleted_at: float  # Unix time.
    data: Path         # The item itself, inside the bin.
    record: Path       # The bin's record of it.


def supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


# --- Windows ---------------------------------------------------------------

def parse_windows_record(raw: bytes) -> tuple[str, float] | None:
    """An $I file: version, size, FILETIME, then the original path."""
    try:
        version, _size, filetime = struct.unpack_from("<qqq", raw)
        if version == 1:  # Vista to 8.1: fixed 260 characters.
            path = raw[24:24 + 520].decode("utf-16-le")
        elif version == 2:  # Windows 10+: length-prefixed.
            (length,) = struct.unpack_from("<i", raw, 24)
            path = raw[28:28 + length * 2].decode("utf-16-le")
        else:
            return None
    except (struct.error, UnicodeDecodeError):
        return None
    return path.split("\x00", 1)[0], filetime / 10_000_000 - FILETIME_EPOCH


def _windows_bins(original: Path) -> list[Path]:
    bin_root = Path(original.anchor) / "$Recycle.Bin"
    try:
        return [folder for folder in bin_root.iterdir() if folder.is_dir()]
    except OSError:
        return []


def _windows_items(original: Path):
    for folder in _windows_bins(original):
        try:
            records = list(folder.glob("$I*"))
        except OSError:
            continue  # Another user's bin.
        for record in records:
            try:
                parsed = parse_windows_record(record.read_bytes())
            except OSError:
                continue
            if parsed:
                yield Trashed(parsed[0], parsed[1], folder / ("$R" + record.name[2:]), record)


# --- Linux (freedesktop.org trash) -----------------------------------------

def _linux_trash() -> Path:
    data_home = os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "Trash"


def parse_trashinfo(text: str) -> tuple[str, float] | None:
    fields = dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line
    )
    try:
        deleted = time.mktime(time.strptime(fields["DeletionDate"][:19], "%Y-%m-%dT%H:%M:%S"))
        return unquote(fields["Path"]), deleted
    except (KeyError, ValueError):
        return None


def _linux_items(original: Path):
    trash = _linux_trash()
    try:
        records = list((trash / "info").glob("*.trashinfo"))
    except OSError:
        return
    for record in records:
        try:
            parsed = parse_trashinfo(record.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if parsed:
            yield Trashed(parsed[0], parsed[1], trash / "files" / record.stem, record)


# --- Shared ------------------------------------------------------------------

def _items(original: Path):
    if sys.platform == "win32":
        return _windows_items(original)
    if sys.platform.startswith("linux"):
        return _linux_items(original)
    raise RestoreUnsupported("Restore it from the Trash by hand.")


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def find(original: Path, deleted_at: float | None, earliest: float, latest: float) -> Trashed | None:
    """The bin item deleted from `original` closest to `deleted_at`.

    Without a recorded time (older journals), anything deleted from that
    path between `earliest` and `latest` counts.
    """
    matches = []
    for item in _items(original):
        if not _same_path(item.original, str(original)) or not item.data.exists():
            continue
        if deleted_at is not None:
            gap = abs(item.deleted_at - deleted_at)
            if gap <= MATCH_WINDOW:
                matches.append((gap, item))
        elif earliest - MATCH_WINDOW <= item.deleted_at <= latest + MATCH_WINDOW:
            matches.append((abs(item.deleted_at - earliest), item))
    return min(matches, key=lambda match: match[0])[1] if matches else None


def restore(item: Trashed, original: Path) -> None:
    if original.exists() or original.is_symlink():
        raise FileExistsError("something else is there now")
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(item.data), str(original))
    try:
        item.record.unlink()
    except OSError:
        pass  # The item is back; a stale record is harmless.
