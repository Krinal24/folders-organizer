import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any


FILE_CATEGORIES = {
    "documents": {
        ".pdf", ".doc", ".docx", ".txt", ".rtf", ".md", ".epub",
        ".xls", ".xlsx", ".csv", ".ppt", ".pptx",
        ".odt", ".ods", ".odp"
    },
    "images": {
        ".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp",
        ".webp", ".svg", ".tiff", ".ico", ".heic", ".avif"
    },
    "videos": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv",
        ".flv", ".webm", ".m4v"
    },
    "audio": {
        ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"
    },
    "executables": {
        ".exe", ".msi", ".bat", ".cmd", ".com", ".scr",
        ".apk", ".dmg", ".appimage", ".deb"
    },
    "archives": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"
    }
}

# Folders never worth descending into or organizing.
EXCLUDED_DIRS = {
    "node_modules", "__pycache__", ".venv", "venv",
    "$recycle.bin", "system volume information",
}

EXCLUDED_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}

# A folder containing any of these is a project: treat it as one unit.
PROJECT_MARKERS = {
    ".git", "package.json", "pyproject.toml", "requirements.txt",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle", "composer.json",
}
PROJECT_MARKER_SUFFIXES = (".sln", ".csproj", ".xcodeproj")

# Stop scanning after this many items so a huge folder can't hang the app.
MAX_ITEMS = 50_000

# Windows attributes for OneDrive "online-only" placeholders.
_CLOUD_ONLY_ATTRS = 0x00400000 | 0x00001000  # RECALL_ON_DATA_ACCESS | OFFLINE


def get_file_category(file_path: Path) -> str:
    extension = file_path.suffix.lower()

    for category, extensions in FILE_CATEGORIES.items():
        if extension in extensions:
            return category

    return "unknown"


def _is_project_dir(path: Path) -> bool:
    try:
        names = {name.lower() for name in os.listdir(path)}
    except OSError:
        return False

    return bool(names & PROJECT_MARKERS) or any(
        name.endswith(PROJECT_MARKER_SUFFIXES) for name in names
    )


def _is_link(entry: os.DirEntry) -> bool:
    # Junctions aren't symlinks but can loop just the same.
    return entry.is_symlink() or entry.is_junction()


def _is_system_file(stats: os.stat_result) -> bool:
    attrs = getattr(stats, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_SYSTEM)


def _folder_totals(path: Path) -> tuple[int, int]:
    """Total size and file count of a folder, without following links."""
    size = 0
    count = 0
    stack = [path]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if _is_link(entry):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            size += entry.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue

    return size, count


def scan_folder(folder_path: str) -> dict[str, Any]:
    root = Path(folder_path).expanduser()

    if not root.exists():
        raise FileNotFoundError(f"Folder not found: {root}")

    if not root.is_dir():
        raise ValueError(f"Path is not a directory: {root}")

    items = []
    skipped = []
    truncated = False
    stack = [root]

    while stack and not truncated:
        current = stack.pop()

        try:
            with os.scandir(current) as entries:
                entries = list(entries)
        except OSError as error:
            skipped.append({
                "relative_path": str(current.relative_to(root)),
                "reason": error.strerror or type(error).__name__,
            })
            continue

        for entry in entries:
            if len(items) >= MAX_ITEMS:
                truncated = True
                break

            entry_path = Path(entry.path)
            relative_path = str(entry_path.relative_to(root))

            try:
                if _is_link(entry):
                    skipped.append({
                        "relative_path": relative_path,
                        "reason": "Link or junction",
                    })
                    continue

                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() in EXCLUDED_DIRS:
                        continue

                    if _is_project_dir(entry_path):
                        size, file_count = _folder_totals(entry_path)
                        items.append({
                            "kind": "folder",
                            "name": entry.name,
                            "relative_path": relative_path,
                            "extension": "",
                            "category": "projects",
                            "size": size,
                            "modified": entry.stat(follow_symlinks=False).st_mtime,
                            "file_count": file_count,
                        })
                    else:
                        stack.append(entry_path)
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue

                if entry.name.lower() in EXCLUDED_FILES:
                    continue

                stats = entry.stat(follow_symlinks=False)

                if _is_system_file(stats):
                    continue

                attrs = getattr(stats, "st_file_attributes", 0)

                items.append({
                    "kind": "file",
                    "name": entry.name,
                    "relative_path": relative_path,
                    "extension": entry_path.suffix.lower(),
                    "category": get_file_category(entry_path),
                    "size": stats.st_size,
                    "modified": stats.st_mtime,
                    "cloud_only": bool(attrs & _CLOUD_ONLY_ATTRS),
                })

            except OSError as error:
                skipped.append({
                    "relative_path": relative_path,
                    "reason": error.strerror or type(error).__name__,
                })

    counts = Counter()
    sizes = Counter()

    for item in items:
        counts[item["category"]] += 1
        sizes[item["category"]] += item["size"]

    return {
        "path": str(root),
        "total_items": len(items),
        "total_files": sum(
            item["file_count"] if item["kind"] == "folder" else 1
            for item in items
        ),
        "total_size": sum(sizes.values()),
        "counts": dict(counts),
        "sizes": dict(sizes),
        "items": items,
        "skipped": skipped,
        "truncated": truncated,
    }
