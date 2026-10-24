import json
import os
from typing import Any

from huggingface_hub import InferenceClient
from dotenv import load_dotenv

from app.ai.analyzer import AIAnalyzer
from app.models.ai_schemas import CleanupPlan


load_dotenv()


class HuggingFaceAnalyzer(AIAnalyzer):

    def __init__(self):
        self.api_token = os.getenv("HF_API_TOKEN")
        self.model = os.getenv(
            "HF_MODEL",
            "Qwen/Qwen3-4B-Instruct-2507"
        )

        if not self.api_token:
            raise ValueError(
                "HF_API_TOKEN is not configured."
            )

        self.client = InferenceClient(
            api_key=self.api_token
        )

    def analyze(
        self,
        files: list[dict[str, Any]]
    ) -> CleanupPlan:

        prompt = self._build_prompt(files)

        response = self.client.chat_completion(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a file organization assistant. "
                        "Analyze files carefully and return only "
                        "the requested stru ctured output."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=4000,
        )
        print(response.choices[0].message.content)

        content = response.choices[0].message.content

        return self._parse_response(content)

    def _build_prompt(
        self,
        files: list[dict[str, Any]]
    ) -> str:

        file_list = json.dumps(
            files,
            indent=2
        )

        
        return f"""
Analyze the following files and create a safe organization plan.

Return ONLY a valid JSON array containing exactly one object
for every input file.

Every object MUST contain exactly these fields:
- relative_path
- category
- subcategory
- action
- destination
- confidence
- reason

Requirements:

1. relative_path:
   Copy the EXACT relative_path from the input.
   Never substitute the filename or modify the path.

2. category:
   Must be exactly one of:
   documents, images, videos, audio, executables, archives, unknown.

3. subcategory:
   Use a short, meaningful label, such as resumes,
   study_materials, photos, software_installs, financial,
   project_backups, or unknown_files.

4. action:
   Must be exactly one of: move, keep, review.

5. destination:
   For "move", provide a relative destination folder.
   For "keep" or "review", return null.
   Never provide an absolute filesystem path.

6. confidence:
   A number between 0 and 1.
   Base confidence on the available evidence.
   Do not claim to know image or document contents from a filename alone.

7. reason:
   Briefly explain the decision using only the filename,
   extension, relative path, and supplied metadata.

Safety rules:
- Never recommend deleting files.
- Mark executable files for review by default.
- Mark unknown or ambiguous files for review.
- Preserve each input relative_path exactly.
- Do not invent file contents.
- Avoid unnecessarily nested destination folders.
- Return one result per input file, with no duplicates.

Return only the JSON array.
Do not use Markdown code fences or add commentary.

Files:
{file_list}
"""


    def _parse_response(
    self,
    content: str
) -> CleanupPlan:

        cleaned = content.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "")
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

        data = json.loads(cleaned)

        # Qwen returned a list directly instead of:
        # {"analyses": [...]}
        #
        # Normalize that response into our internal schema.
        if isinstance(data, list):
            data = {
                "analyses": data
            }

        return CleanupPlan.model_validate(data)