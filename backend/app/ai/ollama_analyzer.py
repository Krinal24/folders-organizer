
import json
from typing import Any

from ollama import chat

from app.ai.analyzer import AIAnalyzer
from app.models.ai_schemas import CleanupPlan


class OllamaAnalyzer(AIAnalyzer):
    def __init__(self):
        self.model = "gemma3:4b"

    def analyze(
        self,
        files: list[dict[str, Any]],
    ) -> CleanupPlan:
        analyses = []

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
                    f"Expected one analysis for {file['relative_path']}, "
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

                if analysis.destination.startswith(("/", "\\")):
                    raise ValueError(
                        f"Absolute destination rejected for "
                        f"{analysis.relative_path}"
                    )

            elif analysis.destination is not None:
                raise ValueError(
                    f"Unexpected destination for {analysis.relative_path}"
                )

            analyses.append(analysis)

        return CleanupPlan(analyses=analyses)
