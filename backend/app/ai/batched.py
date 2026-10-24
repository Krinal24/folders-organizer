import os
import re
from abc import abstractmethod
from typing import Any, Iterator, get_args

from app.ai.analyzer import AIAnalyzer
from app.ai.prompts import (
    CATEGORY_GROUP,
    FIRST_ID,
    GROUPS,
    build_batch_prompt,
    build_system_prompt,
    existing_folders,
    parent_folder,
)
from app.models.ai_schemas import CleanupPlan, FileAnalysis
from app.models.schemas import Category


DEFAULT_BATCH_SIZE = 40

# Confidence 1-9 from the model; at or below this, ask the user to review.
REVIEW_BELOW = 4

# Reason to show when the model leaves it out.
DEFAULT_REASON = "Suggested by the AI."

# Confidence to assume when the model leaves it out.
DEFAULT_CONFIDENCE = 6

# "12|resumes|8|resume in name". Only the id and label are required: small
# models sometimes drift into "12 | resumes | <file name>" mid-reply, and
# the label is still a usable answer.
ANSWER_LINE = re.compile(r"^\s*(\d+)\s*\|\s*([^|]+?)\s*(?:\|(.*))?$")
CONFIDENCE_FIELD = re.compile(r"^\s*([1-9])\s*$")

# Budget per item for the reply, so a rambling model can't run forever.
OUTPUT_TOKENS_PER_ITEM = 25


class BatchedAnalyzer(AIAnalyzer):
    """
    Sends files to the model in batches with one shared, numbered folder
    list, and streams results line by line as the model writes them.
    Providers only implement _stream_completion.
    """

    def __init__(self):
        self.batch_size = int(os.getenv("AI_BATCH_SIZE", DEFAULT_BATCH_SIZE))

    @abstractmethod
    def _stream_completion(
        self,
        system: str,
        user: str,
        max_tokens: int,
    ) -> Iterator[str]:
        """Yield the model's reply as text chunks."""
        raise NotImplementedError

    def analyze(self, files: list[dict[str, Any]]) -> CleanupPlan:
        return CleanupPlan(analyses=list(self.analyze_stream(files)))

    def analyze_stream(
        self,
        files: list[dict[str, Any]],
    ) -> Iterator[FileAnalysis]:
        existing = existing_folders(files)
        groups = {}

        for file in files:
            group = CATEGORY_GROUP.get(file.get("category"))
            if group is None:
                # Other types are filed by rules before reaching the AI.
                yield review_fallback(file, "No AI folder options for this type.")
            else:
                groups.setdefault(group, []).append(file)

        for group, group_files in groups.items():
            folders = GROUPS[group]["folders"] + existing
            system = build_system_prompt(group, folders)
            decoy = GROUPS[group]["decoy"]

            for start in range(0, len(group_files), self.batch_size):
                batch = group_files[start:start + self.batch_size]
                yield from self._analyze_batch(system, folders, batch, decoy)

    def _analyze_batch(self, system, folders, batch, decoy, retry=True):
        chunks = self._stream_completion(
            system,
            build_batch_prompt(batch, decoy),
            max_tokens=len(batch) * OUTPUT_TOKENS_PER_ITEM,
        )
        destinations = {label: path for label, path, _ in folders}
        answered = set()

        for line in _lines(chunks):
            parsed = _parse_line(line, len(batch), destinations)
            if parsed is None or parsed[0] in answered:
                continue

            index, label, confidence, reason = parsed
            answered.add(index)
            yield _to_analysis(batch[index], label, confidence, reason, destinations)

        missing = [file for index, file in enumerate(batch) if index not in answered]

        if missing and retry:
            # A fresh, smaller request usually gets these right.
            yield from self._analyze_batch(system, folders, missing, decoy, retry=False)
        else:
            for file in missing:
                yield review_fallback(file, "The AI didn't give a usable answer.")


def _parse_line(line, batch_size, destinations):
    """(index, label, confidence, reason) or None if the line is unusable."""
    match = ANSWER_LINE.match(line)
    if not match:
        return None

    # The decoy (id 1) maps to -1 and is dropped below.
    index = int(match.group(1)) - FIRST_ID
    label = match.group(2).strip().strip("\"'").lower()

    if not 0 <= index < batch_size:
        return None
    if label != "review" and label not in destinations:
        return None

    fields = (match.group(3) or "").split("|")
    confidence = CONFIDENCE_FIELD.match(fields[0])

    if confidence:
        reason = fields[1].strip() if len(fields) > 1 else ""
        return index, label, int(confidence.group(1)), reason

    # Drifted format: whatever follows isn't a confidence or a reason.
    return index, label, DEFAULT_CONFIDENCE, ""


def _lines(chunks: Iterator[str]) -> Iterator[str]:
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        *complete, buffer = buffer.split("\n")
        yield from complete
    if buffer:
        yield buffer


def _category(file: dict[str, Any]) -> str:
    category = file.get("category")
    return category if category in get_args(Category) else "unknown"


def _already_in(file, destination: str) -> bool:
    parent = parent_folder(file["relative_path"]).lower()
    destination = destination.lower()
    return parent == destination or parent.startswith(destination + "/")


def _to_analysis(file, label, confidence, reason, destinations) -> FileAnalysis:
    if label != "review" and label not in destinations:
        return review_fallback(file, f"The AI picked an unknown folder ({label}).")

    reason = reason or DEFAULT_REASON
    destination = destinations.get(label)

    if destination is None:
        action = "review"
    elif confidence < REVIEW_BELOW:
        action = "review"
        reason = f"Not sure, maybe {destination}: {reason}"
        destination = None
    elif _already_in(file, destination):
        action = "keep"
        reason = f"Already in {destination}: {reason}"
        destination = None
    else:
        action = "move"

    return FileAnalysis(
        relative_path=file["relative_path"],
        category=_category(file),
        subcategory=(destination or "other").split("/")[-1].lower(),
        action=action,
        destination=destination,
        confidence=confidence / 10,
        reason=reason,
    )


def review_fallback(file: dict[str, Any], reason: str) -> FileAnalysis:
    return FileAnalysis(
        relative_path=file["relative_path"],
        category=_category(file),
        subcategory="other",
        action="review",
        confidence=0.0,
        reason=reason,
    )
