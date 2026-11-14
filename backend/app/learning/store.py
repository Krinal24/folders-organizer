import json
import time
import uuid
from pathlib import PureWindowsPath
from threading import Lock
from typing import Any

from app.ai.analyzer import is_safe_destination
from app.storage import data_dir, write_json


# Oldest corrections are dropped beyond this; recent ones matter most.
MAX_CORRECTIONS = 500

MIN_PATTERN, MAX_PATTERN = 2, 80

RULE_ACTIONS = {"move", "keep"}

_lock = Lock()


class InvalidRule(ValueError):
    pass


def _file():
    return data_dir() / "learned.json"


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"rules": data.get("rules", []), "corrections": data.get("corrections", [])}


def _clean_destination(destination: str | None) -> str | None:
    if destination is None:
        return None
    destination = destination.strip().replace("\\", "/").strip("/")
    return destination if is_safe_destination(destination) else None


# --- Rules the user confirmed: "names containing X go to Y" -----------------

def list_rules() -> list[dict[str, Any]]:
    return _load()["rules"]


def add_rule(contains: str, action: str, destination: str | None = None) -> dict[str, Any]:
    contains = contains.strip()
    if not MIN_PATTERN <= len(contains) <= MAX_PATTERN:
        raise InvalidRule(f"The text to match must be {MIN_PATTERN} to {MAX_PATTERN} characters.")
    if action not in RULE_ACTIONS:
        raise InvalidRule("A rule can move files or keep them where they are.")

    if action == "move":
        destination = _clean_destination(destination)
        if not destination:
            raise InvalidRule("Pick a folder inside the scanned folder, like Documents/Study.")
    else:
        destination = None

    rule = {
        "id": uuid.uuid4().hex[:12],
        "contains": contains,
        "action": action,
        "destination": destination,
        "created": time.time(),
        "hits": 0,
    }

    with _lock:
        data = _load()
        # A newer rule for the same text replaces the old one.
        data["rules"] = [
            r for r in data["rules"] if r["contains"].lower() != contains.lower()
        ] + [rule]
        write_json(_file(), data)
    return rule


def delete_rule(rule_id: str) -> None:
    with _lock:
        data = _load()
        remaining = [r for r in data["rules"] if r["id"] != rule_id]
        if len(remaining) == len(data["rules"]):
            raise FileNotFoundError("No such rule.")
        data["rules"] = remaining
        write_json(_file(), data)


def matching_rule(name: str, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The most specific rule whose text appears in the name (case ignored)."""
    lowered = name.lower()
    matches = [r for r in rules if r["contains"].lower() in lowered]
    return max(matches, key=lambda r: len(r["contains"]), default=None)


def record_hits(rule_ids: list[str]) -> None:
    if not rule_ids:
        return
    with _lock:
        data = _load()
        for rule in data["rules"]:
            rule["hits"] += rule_ids.count(rule["id"])
        write_json(_file(), data)


# --- Corrections: what the user changed before applying a plan ---------------

def record_corrections(corrections: list[dict[str, Any]]) -> None:
    if not corrections:
        return
    now = time.time()
    cleaned = []
    for correction in corrections:
        name = PureWindowsPath(correction.get("relative_path") or "").name
        if not name:
            continue
        cleaned.append({
            "name": name,
            "category": correction.get("category"),
            "suggested_action": correction.get("suggested_action"),
            "suggested_destination": correction.get("suggested_destination"),
            "chosen_action": correction.get("chosen_action"),
            "chosen_destination": _clean_destination(correction.get("chosen_destination")),
            "at": now,
        })

    with _lock:
        data = _load()
        # The newest correction for a name wins.
        names = {c["name"].lower() for c in cleaned}
        kept = [c for c in data["corrections"] if c["name"].lower() not in names]
        data["corrections"] = (kept + cleaned)[-MAX_CORRECTIONS:]
        write_json(_file(), data)


def list_corrections() -> list[dict[str, Any]]:
    return _load()["corrections"]


def clear_corrections() -> None:
    with _lock:
        data = _load()
        data["corrections"] = []
        write_json(_file(), data)
