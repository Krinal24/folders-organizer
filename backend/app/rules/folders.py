"""Prefer folders the user already has over creating look-alikes.

The AI and the rules suggest standard destinations such as Documents/Resumes.
If the scanned folder already has RESUMES or CV, files should go there
instead of into a new folder next to it.
"""
import re
from pathlib import PureWindowsPath
from typing import Any


# Look only this deep for existing folders: Resume, or Documents/Resume.
MAX_DEPTH = 2

# Names that mean the same folder, in normalized form (see _key).
SYNONYMS = [
    {"resume", "cv"},
    {"photo", "picture", "pic"},
    {"video", "movie"},
    {"music", "song"},
    {"installer", "setup"},
    {"archive", "zip"},
    {"screenshot", "snip"},
]


def _key(name: str) -> str:
    """"RESUMES", "Resume", "re-sume" -> "resume"."""
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    if len(key) > 2 and key.endswith("s"):
        key = key[:-1]
    return key


def _equivalents(name: str) -> set[str]:
    key = _key(name)
    for group in SYNONYMS:
        if key in group:
            return group
    return {key}


def existing_folders(scan: dict[str, Any]) -> list[str]:
    """Folders that exist in the scan, up to MAX_DEPTH, as posix paths."""
    folders = set()
    paths = [item["relative_path"] for item in scan["items"]]
    for path in paths + list(scan.get("empty_folders", [])):
        parts = PureWindowsPath(path).parts
        # An item's own path is a folder only for empty folders; for files
        # and bundles, their parents are.
        is_folder = path in scan.get("empty_folders", [])
        parents = parts if is_folder else parts[:-1]
        for depth in range(1, min(len(parents), MAX_DEPTH) + 1):
            folders.add("/".join(parents[:depth]))
    return sorted(folders)


def find_existing(destination: str, folders: list[str]) -> str | None:
    """The user's folder that matches destination, if any."""
    by_lower = {folder.lower(): folder for folder in folders}
    if destination.lower() in by_lower:
        return by_lower[destination.lower()]

    wanted = _equivalents(destination.split("/")[-1])
    matches = [f for f in folders if _key(f.split("/")[-1]) in wanted]
    if not matches:
        return None

    # Prefer one under the same parent (Documents/CV for Documents/Resumes),
    # then the shallowest.
    def parent_of(path):
        return path.rsplit("/", 1)[0].lower() if "/" in path else ""

    def rank(folder):
        return (parent_of(folder) != parent_of(destination), folder.count("/"), folder)

    return min(matches, key=rank)


def _already_in(relative_path: str, folder: str) -> bool:
    parent = PureWindowsPath(relative_path).parent.as_posix().lower()
    folder = folder.lower()
    return parent == folder or parent.startswith(folder + "/")


def adopt_existing(suggestion: dict[str, Any], folders: list[str]) -> dict[str, Any]:
    """Point a move at the user's matching folder instead of a new one."""
    destination = suggestion.get("destination")
    if suggestion.get("action") != "move" or not destination:
        return suggestion
    if suggestion.get("rule") == "learned":
        return suggestion  # The user chose that folder explicitly.

    existing = find_existing(destination, folders)
    if existing is None or existing == destination:
        return suggestion

    if _already_in(suggestion["relative_path"], existing):
        return {
            **suggestion,
            "action": "keep",
            "destination": None,
            "reason": f"Already in your {existing} folder.",
        }
    return {
        **suggestion,
        "destination": existing,
        "reason": f"{suggestion['reason']} Using your existing {existing} folder.",
    }
