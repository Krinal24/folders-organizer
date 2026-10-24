import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

from send2trash import send2trash

from app.ai.analyzer import is_safe_destination


# Allowed difference between the analyzed and current modified time.
MTIME_TOLERANCE = 0.01

JOURNAL_ID = re.compile(r"^[0-9A-Za-z_-]+$")


def journal_dir() -> Path:
    """Undo journals live in app data, not in the user's folder."""
    override = os.getenv("JOURNAL_DIR")
    if override:
        return Path(override)
    base = os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share"
    return Path(base) / "FolderOrganizer" / "journals"


def _resolve_root(folder_path: str) -> Path:
    root = Path(folder_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Folder not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Path is not a directory: {root}")
    return root


def _inside(root: Path, path: Path) -> bool:
    return path != root and path.is_relative_to(root)


def _unique_target(target: Path) -> Path:
    """'report.pdf' -> 'report (1).pdf' if taken. Never overwrite."""
    if not target.exists():
        return target
    counter = 1
    while True:
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _changed_since_analysis(path: Path, operation: dict[str, Any]) -> bool:
    stats = path.stat()
    if operation.get("modified") is not None:
        if abs(stats.st_mtime - operation["modified"]) > MTIME_TOLERANCE:
            return True
    if path.is_file() and operation.get("size") is not None:
        if stats.st_size != operation["size"]:
            return True
    return False


def _order(operations):
    # Delete files first, then move, then remove folders (which may only
    # become safe to remove once their contents have been handled).
    def rank(op):
        if op["action"] == "delete":
            return 2 if op.get("kind") == "folder" else 0
        return 1
    return sorted(operations, key=rank)


def execute_plan(
    folder_path: str,
    operations: list[dict[str, Any]],
    trash: Callable[[str], None] = send2trash,
) -> Iterator[dict[str, Any]]:
    """
    Validate the root immediately (so bad paths raise before streaming),
    then return an iterator of events:

      {"type": "started", "journal_id", "total"}
      {"type": "result", "relative_path", "action", "status", "detail", "new_path"}
          status is "done", "skipped" (nothing to do / unsafe / changed)
          or "failed" (the operating system refused)
      {"type": "done", "done", "skipped", "failed", "freed", "journal_id"}

    The journal is saved after every change, so a run that is stopped
    or crashes halfway can still be undone.
    """
    root = _resolve_root(folder_path)

    def events():
        journal_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        journal = {"root": str(root), "created": time.time(), "entries": [], "created_dirs": []}
        counts = {"done": 0, "skipped": 0, "failed": 0}
        freed = 0

        yield {"type": "started", "journal_id": journal_id, "total": len(operations)}

        for operation in _order(operations):
            result = _apply(root, operation, trash, journal)
            counts[result["status"]] += 1
            if result["status"] == "done":
                _save_journal(journal_id, journal)
                if operation["action"] == "delete":
                    freed += operation.get("size") or 0
            yield {"type": "result", **result}

        yield {
            "type": "done",
            **counts,
            "freed": freed,
            "journal_id": journal_id if journal["entries"] else None,
        }

    return events()


def _apply(root, operation, trash, journal) -> dict[str, Any]:
    relative_path = operation["relative_path"]
    action = operation["action"]

    def result(status, detail, new_path=None):
        return {
            "relative_path": relative_path,
            "action": action,
            "status": status,
            "detail": detail,
            "new_path": new_path,
        }

    source = (root / relative_path).resolve()
    # Resolving follows links, so this also catches links pointing outside.
    if not _inside(root, source):
        return result("skipped", "Path is outside the selected folder.")
    if (root / relative_path).is_symlink():
        return result("skipped", "Links are never moved or deleted.")
    if not source.exists():
        return result("skipped", "No longer exists.")

    try:
        if _changed_since_analysis(source, operation):
            return result("skipped", "Changed since the analysis. Scan again first.")

        if action == "delete":
            if operation.get("rule") == "empty_folder" and any(source.iterdir()):
                return result("skipped", "Folder is no longer empty.")
            trash(str(source))
            journal["entries"].append({"op": "delete", "path": relative_path})
            return result("done", "Moved to the Recycle Bin.")

        destination = operation.get("destination")
        if not destination or not is_safe_destination(destination):
            return result("skipped", "Unsafe or missing destination.")

        target_dir = (root / destination).resolve()
        if not _inside(root, target_dir):
            return result("skipped", "Destination is outside the selected folder.")
        if source.parent == target_dir:
            return result("skipped", "Already in that folder.")
        if source.is_dir() and target_dir.is_relative_to(source):
            return result("skipped", "Can't move a folder into itself.")

        _make_dirs(root, target_dir, journal)
        target = _unique_target(target_dir / source.name)
        shutil.move(str(source), str(target))

        new_path = str(target.relative_to(root))
        journal["entries"].append({"op": "move", "from": relative_path, "to": new_path})
        renamed = target.name != source.name
        return result(
            "done",
            f"Moved and renamed to {target.name} (name was taken)." if renamed else "Moved.",
            new_path,
        )

    except OSError as error:
        return result("failed", error.strerror or str(error))


def _make_dirs(root: Path, target_dir: Path, journal) -> None:
    missing = []
    current = target_dir
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    # Outermost first, so undo can remove them innermost first.
    for folder in reversed(missing):
        journal["created_dirs"].append(str(folder.relative_to(root)))


def _save_journal(journal_id: str, journal) -> None:
    folder = journal_dir()
    folder.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash never leaves a half-written journal.
    temporary = folder / f"{journal_id}.json.tmp"
    temporary.write_text(json.dumps(journal, indent=2), encoding="utf-8")
    os.replace(temporary, folder / f"{journal_id}.json")


def undo(journal_id: str) -> dict[str, Any]:
    """Move files back and remove folders the run created, if still empty.

    Deleted files can't be restored automatically; they are in the Recycle Bin.
    """
    if not JOURNAL_ID.match(journal_id):
        raise ValueError("Invalid journal id.")
    journal_file = journal_dir() / f"{journal_id}.json"
    if not journal_file.exists():
        raise FileNotFoundError("Nothing to undo for this run.")

    journal = json.loads(journal_file.read_text(encoding="utf-8"))
    root = Path(journal["root"])
    restored = 0
    problems = []

    for entry in reversed(journal["entries"]):
        if entry["op"] != "move":
            continue
        current = root / entry["to"]
        original = root / entry["from"]
        if not current.exists():
            problems.append(f"{entry['to']}: no longer there")
            continue
        if original.exists():
            problems.append(f"{entry['from']}: something else is there now")
            continue
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(original))
            restored += 1
        except OSError as error:
            problems.append(f"{entry['to']}: {error.strerror or error}")

    for folder in reversed(journal["created_dirs"]):
        try:
            (root / folder).rmdir()  # Only succeeds when empty.
        except OSError:
            pass

    journal_file.unlink()
    return {
        "restored": restored,
        "problems": problems,
        "in_recycle_bin": sum(1 for e in journal["entries"] if e["op"] == "delete"),
    }
