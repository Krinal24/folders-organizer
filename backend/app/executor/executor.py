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
from app.executor import recycle_bin
from app.storage import data_dir, write_json


# Allowed difference between the analyzed and current modified time.
MTIME_TOLERANCE = 0.01

JOURNAL_ID = re.compile(r"^[0-9A-Za-z_-]+$")


def journal_dir() -> Path:
    """Undo journals live in app data, not in the user's folder."""
    override = os.getenv("JOURNAL_DIR")
    return Path(override) if override else data_dir() / "journals"


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
        journal = {
            "root": str(root),
            "created": time.time(),
            "finished": None,
            "completed": False,
            "entries": [],
            "created_dirs": [],
        }
        counts = {"done": 0, "skipped": 0, "failed": 0}
        freed = 0

        try:
            yield {"type": "started", "journal_id": journal_id, "total": len(operations)}

            for operation in _order(operations):
                result = _apply(root, operation, trash, journal)
                counts[result["status"]] += 1
                if result["status"] == "done":
                    _save_journal(journal_id, journal)
                    if operation["action"] == "delete":
                        freed += operation.get("size") or 0
                yield {"type": "result", **result}

            journal["completed"] = True
            yield {
                "type": "done",
                **counts,
                "freed": freed,
                "journal_id": journal_id if journal["entries"] else None,
            }
        finally:
            # Also runs when the client stops the run halfway.
            if journal["entries"]:
                journal["finished"] = time.time()
                _save_journal(journal_id, journal)

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
            journal["entries"].append({
                "op": "delete",
                "path": relative_path,
                "size": operation.get("size") or 0,
                # Lets undo find this exact item in the Recycle Bin.
                "deleted_at": time.time(),
            })
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
    write_json(journal_dir() / f"{journal_id}.json", journal)


class AlreadyUndone(Exception):
    pass


def _journal_file(journal_id: str) -> Path:
    if not JOURNAL_ID.match(journal_id):
        raise ValueError("Invalid run id.")
    journal_file = journal_dir() / f"{journal_id}.json"
    if not journal_file.exists():
        raise FileNotFoundError("No record of this run.")
    return journal_file




def _load(journal_file: Path) -> dict[str, Any]:
    journal = json.loads(journal_file.read_text(encoding="utf-8"))
    old = journal.get("undone")
    if old and "restored" in old:
        # Before per-file undo, one flag covered the whole run, and only
        # moves were put back. Deletes from such runs can still be restored.
        for entry in journal["entries"]:
            if entry["op"] == "move":
                entry.setdefault("undone", old["at"])
        journal["undone"] = None
    return journal


def _summary(journal_id: str, journal: dict[str, Any]) -> dict[str, Any]:
    entries = journal["entries"]
    moves = [e for e in entries if e["op"] == "move"]
    deletes = [e for e in entries if e["op"] == "delete"]
    undone = [e["undone"] for e in entries if e.get("undone")]
    return {
        "id": journal_id,
        "root": journal["root"],
        "created": journal["created"],
        "finished": journal.get("finished"),
        # Older journals predate this flag; treat them as complete.
        "completed": journal.get("completed", True),
        "moved": len(moves),
        "deleted": len(deletes),
        "freed": sum(e.get("size", 0) for e in deletes),
        "undone": len(undone),
        "undone_at": max(undone) if undone else None,
        "pending": len(entries) - len(undone),
        "can_undo": len(undone) < len(entries),
        "can_restore_deletes": recycle_bin.supported(),
    }


def list_runs() -> list[dict[str, Any]]:
    """Every recorded run, newest first."""
    folder = journal_dir()
    if not folder.exists():
        return []

    runs = []
    for journal_file in folder.glob("*.json"):
        try:
            runs.append(_summary(journal_file.stem, _load(journal_file)))
        except (OSError, ValueError, KeyError):
            continue  # A damaged journal shouldn't hide the others.
    return sorted(runs, key=lambda run: run["created"], reverse=True)


def get_run(journal_id: str) -> dict[str, Any]:
    journal = _load(_journal_file(journal_id))
    return {**_summary(journal_id, journal), "entries": journal["entries"]}


class UndoProblem(Exception):
    pass


def _undo_move(root: Path, entry: dict[str, Any]) -> None:
    current = (root / entry["to"]).resolve()
    original = (root / entry["from"]).resolve()
    if not (_inside(root, current) and _inside(root, original)):
        raise UndoProblem("outside the folder, skipped")
    if not current.exists():
        raise UndoProblem(f"no longer at {entry['to']}")
    if original.exists():
        raise UndoProblem("something else is there now")
    try:
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(current), str(original))
    except OSError as error:
        raise UndoProblem(error.strerror or str(error))


def _undo_delete(root: Path, journal: dict[str, Any], entry: dict[str, Any]) -> None:
    original = (root / entry["path"]).resolve()
    if not _inside(root, original):
        raise UndoProblem("outside the folder, skipped")
    if not recycle_bin.supported():
        raise UndoProblem("restore it from the Trash by hand")
    item = recycle_bin.find(
        original,
        entry.get("deleted_at"),
        earliest=journal["created"],
        latest=journal.get("finished") or time.time(),
    )
    if item is None:
        raise UndoProblem("not in the Recycle Bin any more (emptied or already restored?)")
    try:
        recycle_bin.restore(item, original)
    except FileExistsError:
        raise UndoProblem("something else is there now")
    except OSError as error:
        raise UndoProblem(error.strerror or str(error))


def undo(journal_id: str, indices: list[int] | None = None) -> dict[str, Any]:
    """Put back the chosen entries of a run, or all of them.

    Moved files go back where they were; deleted ones come back out of the
    Recycle Bin. Each entry is marked as undone on its own, so the rest of
    the run can still be undone later. Folders the run created are removed
    once they are empty.
    """
    journal_file = _journal_file(journal_id)
    journal = _load(journal_file)
    entries = journal["entries"]

    if indices is None:
        chosen = range(len(entries))
    else:
        if any(not 0 <= index < len(entries) for index in indices):
            raise ValueError("No such change in this run.")
        chosen = sorted(set(indices))

    pending = [index for index in chosen if not entries[index].get("undone")]
    if not pending:
        raise AlreadyUndone("Already undone.")

    root = Path(journal["root"]).resolve()
    restored = recovered = 0
    problems = []

    # Newest first, so a chain of changes unwinds in order.
    for index in reversed(pending):
        entry = entries[index]
        try:
            if entry["op"] == "move":
                _undo_move(root, entry)
                restored += 1
            else:
                _undo_delete(root, journal, entry)
                recovered += 1
        except UndoProblem as problem:
            problems.append(f"{entry.get('from') or entry.get('path')}: {problem}")
            continue
        entry["undone"] = time.time()
        _save_journal(journal_id, journal)

    for folder in reversed(journal["created_dirs"]):
        try:
            (root / folder).rmdir()  # Only succeeds when empty.
        except OSError:
            pass

    _save_journal(journal_id, journal)
    still_deleted = sum(
        1 for index in pending
        if entries[index]["op"] == "delete" and not entries[index].get("undone")
    )
    return {
        "restored": restored,
        "recovered": recovered,
        "problems": problems,
        "in_recycle_bin": still_deleted,
    }
