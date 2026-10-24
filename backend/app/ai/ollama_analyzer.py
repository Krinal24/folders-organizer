import json
import os
from typing import Any, Iterator, get_args

from ollama import chat

from app.ai.analyzer import AIAnalyzer, is_safe_destination
from app.models.ai_schemas import CleanupPlan, FileAnalysis
from app.models.schemas import Category


class OllamaAnalyzer(AIAnalyzer):
    def __init__(self):
        self.model = os.getenv("OLLAMA_MODEL", "gemma3:4b")

    def analyze(
        self,
        files: list[dict[str, Any]],
    ) -> CleanupPlan:
        return CleanupPlan(analyses=list(self.analyze_stream(files)))

    def analyze_stream(
        self,
        files: list[dict[str, Any]],
    ) -> Iterator[FileAnalysis]:
        system_prompt = """
You are DownloadMind, a cautious file organization assistant.

Analyze exactly one file per request.

Categories:
documents, images, videos, audio, executables, archives, projects, unknown.

Actions:
move, keep, review.

Rules:
- Return exactly one analysis in the analyses array.
- Copy relative_path exactly from the input.
- Use only the supplied filename and metadata as evidence.
- Never claim to know a file's contents from its name alone.
- Never recommend deletion.
- Executables and unknown files must use action review.
- Items with kind "folder" are self-contained projects. Never split them;
  use action keep or review, or move the whole folder.
- Use meaningful subcategories when there is evidence.
- Use subcategory "other" when the specific subcategory is uncertain.
- Use action move only when there is a reasonable destination.
- For move, destination must be a non-empty relative folder path.
- For keep or review, destination must be null.
- Never use absolute paths.
- Return valid JSON matching the supplied schema.
"""

        for file in files:
            expected_path = (
                file.get("relative_path")
                or file.get("path")
                or file.get("name")
            )

            if not expected_path:
                raise ValueError(
                    f"File metadata is missing a path. "
                    f"Available keys: {list(file.keys())}"
                )

            file_for_ai = {
                **file,
                "relative_path": expected_path,
            }
            try:
                yield self._analyze_one(system_prompt, file_for_ai, expected_path)
            except ValueError as error:
                # One bad answer shouldn't sink the whole folder.
                yield _review_fallback(file_for_ai, error)

    def _analyze_one(
        self,
        system_prompt: str,
        file_for_ai: dict[str, Any],
        expected_path: str,
    ) -> FileAnalysis:
        response = chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze this file:\n"
                        + json.dumps(file_for_ai, ensure_ascii=False)
                    ),
                },
            ],
            format=CleanupPlan.model_json_schema(),
            options={"temperature": 0},
        )

        content = response.message.content
        single_plan = CleanupPlan.model_validate_json(content)

        if len(single_plan.analyses) != 1:
            raise ValueError(
                f"Expected one analysis for {expected_path}, "
                f"but received {len(single_plan.analyses)}."
            )

        analysis = single_plan.analyses[0]

        if analysis.relative_path != expected_path:
            raise ValueError(
                f"AI returned an unexpected path for {expected_path}."
            )

        if analysis.action == "move":
            if not analysis.destination:
                raise ValueError(
                    f"Missing destination for {analysis.relative_path}"
                )

            if not is_safe_destination(analysis.destination):
                raise ValueError(
                    f"Unsafe destination rejected for "
                    f"{analysis.relative_path}"
                )

        elif analysis.destination is not None:
            raise ValueError(
                f"Unexpected destination for {analysis.relative_path}"
            )

        return analysis


def _review_fallback(file: dict[str, Any], error: Exception) -> FileAnalysis:
    category = file.get("category")
    if category not in get_args(Category):
        category = "unknown"

    return FileAnalysis(
        relative_path=file["relative_path"],
        category=category,
        subcategory="other",
        action="review",
        confidence=0.0,
        reason=f"The AI response could not be used ({error}). Please review.",
    )
