import hashlib
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.learning.store import matching_rule
from app.rules.photos import similar_groups


DAY = 24 * 60 * 60

PARTIAL_DOWNLOAD_SUFFIXES = {
    ".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp"
}
# Give in-progress downloads a chance to finish before flagging them.
PARTIAL_DOWNLOAD_MIN_AGE = 1 * DAY

INSTALLER_SUFFIXES = {
    ".exe", ".msi", ".dmg", ".pkg", ".apk", ".deb", ".appimage"
}
INSTALLER_MIN_AGE = 30 * DAY

# "report (1).pdf", "report - Copy.pdf", "report - Copy (2).pdf", "report_copy2.pdf"
COPY_MARKER = re.compile(
    r"(\s\(\d+\)|\s-\sCopy(\s\(\d+\))?|_copy\d*)$",
    re.IGNORECASE,
)

PARTIAL_HASH_BYTES = 64 * 1024

# Types whose destination needs no judgement. Documents and images are
# left to the AI, which picks a subfolder from the name.
TYPE_DESTINATIONS = {
    "videos": "Videos",
    "audio": "Music",
    "archives": "Archives",
    "executables": "Installers",
    "projects": "Projects",
}


def _hash_file(path: Path, limit: int | None = None) -> str | None:
    digest = hashlib.sha256()
    remaining = limit

    try:
        with open(path, "rb") as file:
            while remaining is None or remaining > 0:
                chunk_size = 1024 * 1024
                if remaining is not None:
                    chunk_size = min(chunk_size, remaining)
                chunk = file.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
    except OSError:
        return None

    return digest.hexdigest()


def _group_by(items, key_fn):
    groups = defaultdict(list)
    for item in items:
        key = key_fn(item)
        if key is not None:
            groups[key].append(item)
    return [group for group in groups.values() if len(group) > 1]


def _original_sort_key(item: dict[str, Any]):
    # Keep the copy without a "(1)" marker, then the oldest, then the shortest name.
    has_marker = bool(COPY_MARKER.search(Path(item["name"]).stem))
    return (has_marker, item["modified"], len(item["name"]), item["relative_path"])


def _keeper_sort_key(photo: dict[str, Any]):
    # Keep the sharpest copy: most pixels, then the biggest file, then as
    # for exact duplicates.
    return (-photo["width"] * photo["height"], -photo["size"], *_original_sort_key(photo))


def find_similar_photos(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []

    for group in similar_groups(root, items):
        keeper, *others = sorted(group, key=_keeper_sort_key)
        keeper_size = f"{keeper['width']}×{keeper['height']}"

        for photo in others:
            size = f"{photo['width']}×{photo['height']}"
            detail = (
                f"same size {size}, probably re-saved or forwarded"
                if size == keeper_size
                else f"{size} here vs {keeper_size} kept"
            )
            suggestions.append(_suggestion(
                photo,
                rule="similar_photo",
                confidence=0.6,
                reason=f"Looks like the same photo as {keeper['name']} ({detail}).",
                duplicate_of=keeper["relative_path"],
            ))

    return suggestions


def find_duplicates(root: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        item for item in items
        if item["kind"] == "file"
        and item["size"] > 0
        and not item.get("cloud_only")
    ]

    suggestions = []

    for same_size in _group_by(candidates, lambda item: item["size"]):
        # Cheap pass on the first 64 KB, then confirm with a full hash.
        partial_groups = _group_by(
            same_size,
            lambda item: _hash_file(root / item["relative_path"], PARTIAL_HASH_BYTES),
        )

        for partial_group in partial_groups:
            if partial_group[0]["size"] <= PARTIAL_HASH_BYTES:
                full_groups = [partial_group]
            else:
                full_groups = _group_by(
                    partial_group,
                    lambda item: _hash_file(root / item["relative_path"]),
                )

            for group in full_groups:
                original, *copies = sorted(group, key=_original_sort_key)

                for copy in copies:
                    suggestions.append(_suggestion(
                        copy,
                        rule="duplicate",
                        confidence=0.99,
                        reason="Identical content to another file in this folder.",
                        duplicate_of=original["relative_path"],
                    ))

    return suggestions


def _suggestion(
    item, rule, confidence, reason,
    duplicate_of=None, action="delete", destination=None,
):
    return {
        "relative_path": item["relative_path"],
        "kind": item["kind"],
        "action": action,
        "destination": destination,
        "category": item.get("category"),
        "confidence": confidence,
        "reason": reason,
        "source": "rule",
        "rule": rule,
        "duplicate_of": duplicate_of,
        "size": item.get("size", 0),
        "modified": item.get("modified"),
    }


def _describe_age(seconds: float) -> str:
    days = int(seconds // DAY)
    if days >= 365:
        years = days // 365
        return f"over {years} year{'s' if years > 1 else ''}"
    if days >= 60:
        return f"{days // 30} months"
    return f"{days} days"


def _single_file_rule(item: dict[str, Any], now: float) -> dict[str, Any] | None:
    if item["kind"] != "file":
        return None

    name = item["name"]
    extension = item["extension"]
    age = now - item["modified"]

    if (
        extension in PARTIAL_DOWNLOAD_SUFFIXES or name.startswith("~$")
    ) and age > PARTIAL_DOWNLOAD_MIN_AGE:
        return _suggestion(
            item,
            rule="partial_download",
            confidence=0.9,
            reason="Leftover partial download or temporary file.",
        )

    if item["size"] == 0:
        return _suggestion(
            item,
            rule="empty_file",
            confidence=0.8,
            reason="File is empty (0 bytes).",
        )

    if extension in INSTALLER_SUFFIXES and age > INSTALLER_MIN_AGE:
        return _suggestion(
            item,
            rule="old_installer",
            confidence=0.7,
            reason=f"Downloaded {_describe_age(age)} ago.",
        )

    return None


def _already_under(item: dict[str, Any], destination: str) -> bool:
    parent = Path(item["relative_path"]).parent.as_posix().lower()
    destination = destination.lower()
    return parent == destination or parent.startswith(destination + "/")


def _learned_rule(item: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A rule the user saved, e.g. names containing "21MAT" go to Documents/Study."""
    rule = matching_rule(item["name"], rules)
    if rule is None:
        return None

    base = {"rule": "learned", "confidence": 1.0}
    if rule["action"] == "keep":
        suggestion = _suggestion(
            item, **base, action="keep",
            reason=f'Your rule: keep names containing "{rule["contains"]}" where they are.',
        )
    elif _already_under(item, rule["destination"]):
        suggestion = _suggestion(
            item, **base, action="keep",
            reason=f'Already in {rule["destination"]}, where your rule puts names containing "{rule["contains"]}".',
        )
    else:
        suggestion = _suggestion(
            item, **base, action="move", destination=rule["destination"],
            reason=f'Your rule: names containing "{rule["contains"]}" go to {rule["destination"]}.',
        )
    return {**suggestion, "rule_id": rule["id"]}


def _file_type_rule(item: dict[str, Any]) -> dict[str, Any] | None:
    destination = TYPE_DESTINATIONS.get(item["category"])
    if destination is None or _already_under(item, destination):
        return None

    label = "project" if item["kind"] == "folder" else item["category"].rstrip("s")
    return _suggestion(
        item,
        rule="file_type",
        confidence=0.9,
        reason=f"Group with other {label} files in {destination}.",
        action="move",
        destination=destination,
    )


def _unknown_type_rule(item: dict[str, Any]) -> dict[str, Any] | None:
    if item["kind"] != "file" or item["category"] != "unknown":
        return None
    kind = f'"{item["extension"]}" files' if item["extension"] else "files without an extension"
    return _suggestion(
        item,
        rule="unknown_type",
        confidence=0.0,
        reason=f"TidyByte doesn't know what to do with {kind}. Your call.",
        action="review",
    )


def apply_rules(
    root: Path,
    scan: dict[str, Any],
    now: float | None = None,
    learned_rules: list[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Deterministic cleanup suggestions. At most one suggestion per path."""
    now = time.time() if now is None else now
    suggestions = {}

    # Duplicates first: "identical to X" is the most precise thing we can say.
    for suggestion in find_duplicates(root, scan["items"]):
        suggestions[suggestion["relative_path"]] = suggestion

    # Then the same photo saved differently (resized, re-compressed).
    unmatched = [item for item in scan["items"] if item["relative_path"] not in suggestions]
    for suggestion in find_similar_photos(root, unmatched):
        suggestions[suggestion["relative_path"]] = suggestion

    for item in scan["items"]:
        if item["relative_path"] in suggestions:
            continue
        # The user's own rules come before any of ours.
        suggestion = (
            _learned_rule(item, learned_rules)
            or _single_file_rule(item, now)
            or _file_type_rule(item)
            or _unknown_type_rule(item)
        )
        if suggestion:
            suggestions[item["relative_path"]] = suggestion

    for folder in scan["empty_folders"]:
        suggestions[folder] = _suggestion(
            {"relative_path": folder, "kind": "folder"},
            rule="empty_folder",
            confidence=0.9,
            reason="Folder is empty.",
        )

    return list(suggestions.values())
