import os
from pathlib import Path
from typing import Any, Callable, Iterator

from app.ai.analyzer import AIAnalyzer, is_safe_destination
from app.ai.batched import DEFAULT_REASON
from app.ai.factory import get_analyzer
from app.ai.prompts import CATEGORY_GROUP, GROUPS, existing_folders, parent_folder
from app.content.extract import extract_snippet, name_is_unclear
from app.models.plan_schemas import Suggestion
from app.rules.rules import TYPE_DESTINATIONS, apply_rules
from app.scanner.scanner import scan_folder


# Only what the AI needs to judge an item; no timestamps or local flags.
AI_FIELDS = ("name", "relative_path", "kind", "extension", "category", "size", "file_count")

# Which documents get their text read for the AI: "unclear" (names that
# don't say what the file is), "all", or "off". Reading text costs model
# time, so "unclear" suits a local CPU model; a hosted one can use "all".
CONTENT_MODES = {"unclear", "all", "off"}


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
) -> Iterator[dict[str, Any]]:
    """
    Scan and apply rules immediately (so bad paths raise before streaming),
    then return an iterator of events:

      {"type": "rules", "path", "suggestions", "destinations", "ai_pending"}
      {"type": "ai", "suggestion"}        one per AI result, as it arrives
      {"type": "error", "message"}        the AI failed; earlier results stand
      {"type": "done", "ai_used"}
    """
    # Rescan instead of trusting a file list sent by the client.
    scan = scan_folder(folder_path)
    root = Path(scan["path"])

    rule_suggestions = apply_rules(root, scan)
    handled = {suggestion["relative_path"] for suggestion in rule_suggestions}

    # Only types whose folder depends on the name need the AI.
    remaining = {
        item["relative_path"]: item
        for item in scan["items"]
        if item["relative_path"] not in handled
        and item["category"] in CATEGORY_GROUP
    }
    run_ai = use_ai and bool(remaining)

    def events():
        yield {
            "type": "rules",
            "path": scan["path"],
            "suggestions": [_validated(s) for s in rule_suggestions],
            "destinations": _destinations(scan["items"]),
            "ai_pending": len(remaining) if run_ai else 0,
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
                    yield {"type": "ai", "suggestion": _validated(_unreadable(item))}
                    continue
            for_ai[path] = item

        try:
            analyses = analyzer_factory().analyze_stream([
                {field: item.get(field) for field in (*AI_FIELDS, "snippet")}
                for item in for_ai.values()
            ]) if for_ai else []
            for suggestion in _ai_suggestions(analyses, for_ai):
                yield {"type": "ai", "suggestion": _validated(suggestion)}
        except Exception as error:
            yield {"type": "error", "message": f"{type(error).__name__}: {error}"}
            yield {"type": "done", "ai_used": False}
            return

        yield {"type": "done", "ai_used": True}

    return events()


def build_plan(
    folder_path: str,
    use_ai: bool = True,
    analyzer_factory: Callable[[], AIAnalyzer] = get_analyzer,
    read_contents: bool = True,
) -> dict[str, Any]:
    """Collect the whole stream into one result."""
    result = {"suggestions": [], "ai_error": None}

    for event in stream_plan(folder_path, use_ai, analyzer_factory, read_contents):
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


def _destinations(items: list[dict[str, Any]]) -> list[str]:
    """Every folder the user can pick when overriding a suggestion."""
    paths = set(TYPE_DESTINATIONS.values())
    paths |= {path for group in GROUPS.values() for _, path, _ in group["folders"]}
    paths |= {path for _, path, _ in existing_folders(items)}
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
