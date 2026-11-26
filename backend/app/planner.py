import os
from pathlib import Path
from typing import Any, Callable, Iterator

from app.ai.analyzer import AIAnalyzer, is_safe_destination
from app.ai.batched import DEFAULT_REASON
from app.ai.factory import get_analyzer
from app.ai.prompts import CATEGORY_GROUP, GROUPS, existing_folders, parent_folder
from app.content.extract import SUPPORTED_SUFFIXES, extract_snippet, name_is_unclear
from app.learning.store import list_corrections, list_rules, record_hits
from app.models.plan_schemas import Suggestion
from app.rules import folders as user_folders
from app.rules.rules import TYPE_DESTINATIONS, apply_rules
from app.scanner.scanner import scan_folder


# Only what the AI needs to judge an item; no timestamps or local flags.
AI_FIELDS = ("name", "relative_path", "kind", "extension", "category", "size", "file_count")

# The folder TidyByte itself runs from (the repo, or an installed copy).
APP_DIR = Path(__file__).resolve().parents[2]


def _protect_app(root: Path, suggestion: dict[str, Any]) -> dict[str, Any]:
    """Never move or delete the folder TidyByte is running from."""
    if suggestion["action"] not in ("move", "delete"):
        return suggestion
    target = (root / suggestion["relative_path"]).resolve()
    if APP_DIR != target and not APP_DIR.is_relative_to(target):
        return suggestion
    return {
        **suggestion,
        "action": "keep",
        "destination": None,
        "reason": "TidyByte itself runs from this folder, so it stays where it is.",
    }

# Which documents get their text read for the AI: "unclear" (names that
# don't say what the file is), "all", or "off". Reading text costs model
# time, so "unclear" suits a local CPU model; a hosted one can use "all".
CONTENT_MODES = {"unclear", "all", "off"}


# AI answers below this confidence, or "Other" / "review", get a second
# look: the file's text is read and the AI asked again.
SECOND_LOOK_BELOW = 0.7


def _needs_second_look(suggestion: dict[str, Any], item: dict[str, Any], mode: str) -> bool:
    if mode == "off" or "snippet" in item:  # Its text was already read.
        return False
    if item["extension"] not in SUPPORTED_SUFFIXES:
        return False
    return (
        suggestion["action"] == "review"
        or suggestion["confidence"] < SECOND_LOOK_BELOW
        or (suggestion.get("destination") or "").endswith("/Other")
    )


def _content_mode() -> str:
    mode = os.getenv("AI_READ_CONTENTS", "unclear").lower()
    return mode if mode in CONTENT_MODES else "unclear"


def _wants_content(item: dict[str, Any], mode: str) -> bool:
    return (
        mode != "off"
        and item["kind"] == "file"
        and item["category"] == "documents"
        and not item.get("cloud_only")  # Reading would trigger a download.
        and (mode == "all" or name_is_unclear(item["name"]))
    )


def stream_plan(
    folder_path: str,
    use_ai: bool = True,
    analyzer_factory: Callable[[], AIAnalyzer] = get_analyzer,
    read_contents: bool = True,
    include_subfolders: bool = False,
) -> Iterator[dict[str, Any]]:
    """
    Scan and apply rules immediately (so bad paths raise before streaming),
    then return an iterator of events:

      {"type": "rules", "path", "suggestions", "destinations", "ai_pending",
       "left_alone"}
      {"type": "ai", "suggestion"}        one per AI result, as it arrives
      {"type": "error", "message"}        the AI failed; earlier results stand
      {"type": "done", "ai_used"}
    """
    # Rescan instead of trusting a file list sent by the client.
    scan = scan_folder(folder_path)
    root = Path(scan["path"])

    # By default only loose files are organized: folders the user made are
    # usually organized already, and sorting their contents is slow and can
    # break them (a dataset split from its labels, a course folder scattered).
    plan_scan, left_alone = (scan, None) if include_subfolders else _loose_only(scan)

    rules = list_rules()
    # Folders the user already has, so "Documents/Resumes" becomes their RESUMES.
    folders = user_folders.existing_folders(scan)

    def adopt(suggestion):
        return user_folders.adopt_existing(suggestion, folders)

    rule_suggestions = [
        _protect_app(root, adopt(s))
        for s in apply_rules(root, plan_scan, learned_rules=rules)
    ]
    handled = {suggestion["relative_path"] for suggestion in rule_suggestions}
    record_hits([s["rule_id"] for s in rule_suggestions if s.get("rule_id")])
    corrections = list_corrections()

    # Only types whose folder depends on the name need the AI.
    remaining = {
        item["relative_path"]: item
        for item in plan_scan["items"]
        if item["relative_path"] not in handled
        and item["category"] in CATEGORY_GROUP
    }
    run_ai = use_ai and bool(remaining)

    def events():
        yield {
            "type": "rules",
            "path": scan["path"],
            "suggestions": [_validated(s) for s in rule_suggestions],
            "destinations": _destinations(scan["items"], folders, rules, corrections),
            "ai_pending": len(remaining) if run_ai else 0,
            "left_alone": left_alone,
        }

        if not run_ai:
            yield {"type": "done", "ai_used": False}
            return

        # After the rules event, so reading files never delays it.
        mode = _content_mode() if read_contents else "off"
        for_ai = {}
        for path, item in remaining.items():
            if _wants_content(item, mode):
                item["snippet"] = extract_snippet(root / item["relative_path"])
                if not item["snippet"] and name_is_unclear(item["name"]):
                    # Neither the name nor the text says anything; an AI
                    # answer would be a guess, so don't ask for one.
                    yield {"type": "ai", "suggestion": _validated(adopt(_unreadable(item)))}
                    continue
            for_ai[path] = item

        def ask(analyzer, items):
            return _ai_suggestions(analyzer.analyze_stream(
                [
                    {field: item.get(field) for field in (*AI_FIELDS, "snippet")}
                    for item in items.values()
                ],
                examples=corrections,
                # Existing folders come from the whole scan, not just the
                # loose files being sorted.
                context=scan["items"],
            ), items)

        # First answers the AI wasn't sure about, held back for a second look.
        unsure = {}
        try:
            analyzer = analyzer_factory() if for_ai else None
            for suggestion in ask(analyzer, for_ai) if for_ai else []:
                path = suggestion["relative_path"]
                if _needs_second_look(suggestion, for_ai[path], mode):
                    unsure[path] = suggestion
                else:
                    yield {"type": "ai", "suggestion": _validated(adopt(suggestion))}
        except Exception as error:
            for suggestion in unsure.values():
                yield {"type": "ai", "suggestion": _validated(adopt(suggestion))}
            yield {"type": "error", "message": f"{type(error).__name__}: {error}"}
            yield {"type": "done", "ai_used": False}
            return

        yield from _second_look(root, analyzer, ask, unsure, for_ai, adopt)
        yield {"type": "done", "ai_used": True}

    return events()


def _second_look(root, analyzer, ask, unsure, items, adopt):
    """Ask again about unsure files, this time with their text.

    Text comes from the file itself, or from OCR for scanned PDFs. Every
    held-back file gets exactly one answer: the new one, or the first one
    if there is nothing to read or the AI fails this time.
    """
    readable = {}
    for path, first in unsure.items():
        item = items[path]
        item["snippet"] = extract_snippet(root / item["relative_path"])
        if item["snippet"]:
            readable[path] = item
        else:
            yield {"type": "ai", "suggestion": _validated(adopt(first))}

    answered = set()
    if readable:
        try:
            for suggestion in ask(analyzer, readable):
                answered.add(suggestion["relative_path"])
                yield {"type": "ai", "suggestion": _validated(adopt(suggestion))}
        except Exception:
            pass  # The first answers below are still useful.

    for path in readable.keys() - answered:
        yield {"type": "ai", "suggestion": _validated(adopt(unsure[path]))}


def build_plan(
    folder_path: str,
    use_ai: bool = True,
    analyzer_factory: Callable[[], AIAnalyzer] = get_analyzer,
    read_contents: bool = True,
    include_subfolders: bool = False,
) -> dict[str, Any]:
    """Collect the whole stream into one result."""
    result = {"suggestions": [], "ai_error": None}

    events = stream_plan(folder_path, use_ai, analyzer_factory, read_contents, include_subfolders)
    for event in events:
        if event["type"] == "rules":
            result["path"] = event["path"]
            result["suggestions"].extend(event["suggestions"])
        elif event["type"] == "ai":
            result["suggestions"].append(event["suggestion"])
        elif event["type"] == "error":
            result["ai_error"] = event["message"]
        elif event["type"] == "done":
            result["ai_used"] = event["ai_used"]

    result["reclaimable_size"] = sum(
        suggestion["size"]
        for suggestion in result["suggestions"]
        if suggestion["action"] == "delete"
    )
    return result


def _loose_only(scan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Only items directly in the scanned folder, and what was left alone."""
    loose = [item for item in scan["items"] if not parent_folder(item["relative_path"])]
    nested = [item for item in scan["items"] if parent_folder(item["relative_path"])]
    left_alone = {
        "files": sum(
            (item.get("file_count") or 0) if item["kind"] == "folder" else 1
            for item in nested
        ),
        "folders": len({parent_folder(item["relative_path"]).split("/")[0] for item in nested}),
    }
    plan_scan = {
        **scan,
        "items": loose,
        "empty_folders": [f for f in scan["empty_folders"] if not parent_folder(f)],
    }
    return plan_scan, left_alone


def _destinations(items, folders=(), rules=(), corrections=()) -> list[str]:
    """Every folder the user can pick when overriding a suggestion."""
    defaults = set(TYPE_DESTINATIONS.values())
    defaults |= {path for group in GROUPS.values() for _, path, _ in group["folders"]}
    # Offer the user's RESUMES rather than a look-alike Documents/Resumes.
    paths = {user_folders.find_existing(path, folders) or path for path in defaults}
    paths |= {path for _, path, _ in existing_folders(items)}
    # Folders the user chose before, by rule or by hand.
    paths |= {rule["destination"] for rule in rules if rule.get("destination")}
    paths |= {c["chosen_destination"] for c in corrections if c.get("chosen_destination")}
    return sorted(paths, key=str.lower)


def _validated(suggestion: dict[str, Any]) -> dict[str, Any]:
    # Streaming bypasses FastAPI's response_model, so validate here.
    return Suggestion.model_validate(suggestion).model_dump()


def _unreadable(item: dict[str, Any]) -> dict[str, Any]:
    parent = parent_folder(item["relative_path"])
    base = {
        "relative_path": item["relative_path"],
        "kind": item["kind"],
        "category": item["category"],
        "confidence": 0.5,
        "source": "rule",
        "rule": "unclear_document",
        "size": item["size"],
        "modified": item.get("modified"),
    }
    if parent:
        # The user may have filed it here on purpose; don't second-guess.
        return {
            **base,
            "action": "keep",
            "reason": f"Its name and contents don't say what it is, so it stays in {parent}.",
        }
    return {
        **base,
        "action": "move",
        "destination": "Documents/Other",
        "reason": "Its name and contents don't say what it is (often a scanned image).",
    }


def _ai_suggestions(analyses, items: dict[str, dict[str, Any]]):
    seen = set()

    for analysis in analyses:
        item = items.get(analysis.relative_path)

        # Ignore paths the AI invented or repeated.
        if item is None or analysis.relative_path in seen:
            continue
        seen.add(analysis.relative_path)

        action = analysis.action
        destination = analysis.destination
        reason = analysis.reason

        if item.get("snippet") and DEFAULT_REASON in reason:
            # Small models often skip the reason when given text; showing
            # what the text says is more useful anyway.
            reason = reason.replace(
                DEFAULT_REASON, f'Its text starts: "{item["snippet"][:80]}…"'
            )

        if action == "move" and not (destination and is_safe_destination(destination)):
            action, destination = "review", None
            reason = f"AI proposed an unsafe destination. {reason}"

        yield {
            "relative_path": analysis.relative_path,
            "kind": item["kind"],
            "action": action,
            "destination": destination if action == "move" else None,
            "category": item["category"],
            "subcategory": analysis.subcategory,
            "confidence": analysis.confidence,
            "reason": reason,
            "source": "ai",
            "size": item["size"],
            "modified": item.get("modified"),
            "used_content": bool(item.get("snippet")),
        }
