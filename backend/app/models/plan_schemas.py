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
    "unclear_document",
    "learned",
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
    # For rule "learned": which of the user's saved rules matched.
    rule_id: str | None = None
    duplicate_of: str | None = None
    size: int
    # Lets the executor detect files that changed after the analysis.
    modified: float | None = None
    # The AI saw the start of the file's text, not just its name.
    used_content: bool = False


class AnalyzeRequest(BaseModel):
    path: str
    use_ai: bool = True
    # Let the AI read the start of documents whose names are unclear.
    read_contents: bool = True


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


class Correction(BaseModel):
    """A suggestion the user changed before applying; TidyByte learns from it."""
    relative_path: str
    category: str | None = None
    suggested_action: str | None = None
    suggested_destination: str | None = None
    chosen_action: Literal["move", "keep", "delete"]
    chosen_destination: str | None = None


class ExecuteRequest(BaseModel):
    path: str
    operations: list[Operation] = Field(max_length=100_000)
    corrections: list[Correction] = Field(default=[], max_length=100_000)


class RuleRequest(BaseModel):
    contains: str
    action: Literal["move", "keep"]
    destination: str | None = None


class UndoRequest(BaseModel):
    journal_id: str
