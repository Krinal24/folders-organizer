from typing import Literal

from pydantic import BaseModel, Field

from app.models.schemas import Category


RuleName = Literal[
    "duplicate",
    "partial_download",
    "empty_file",
    "old_installer",
    "empty_folder",
    "file_type",
]


class Suggestion(BaseModel):
    relative_path: str
    kind: Literal["file", "folder"]
    # Only rules may suggest "delete"; the AI is limited to move/keep/review.
    # Rules may also "move" when the file type alone decides the folder.
    action: Literal["move", "keep", "review", "delete"]
    destination: str | None = None
    category: Category | None = None
    subcategory: str | None = None
    confidence: float
    reason: str
    source: Literal["rule", "ai"]
    rule: RuleName | None = None
    duplicate_of: str | None = None
    size: int
    # Lets the executor detect files that changed after the analysis.
    modified: float | None = None


class AnalyzeRequest(BaseModel):
    path: str
    use_ai: bool = True


class Operation(BaseModel):
    """One approved change, as the user confirmed it."""
    relative_path: str
    kind: Literal["file", "folder"] = "file"
    action: Literal["move", "delete"]
    destination: str | None = None
    rule: str | None = None
    # As seen during analysis; files that changed since are skipped.
    size: int | None = None
    modified: float | None = None


class ExecuteRequest(BaseModel):
    path: str
    operations: list[Operation] = Field(max_length=100_000)


class UndoRequest(BaseModel):
    journal_id: str
