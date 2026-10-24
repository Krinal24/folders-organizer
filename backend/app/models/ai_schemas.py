from typing import Literal

from pydantic import BaseModel, Field

from app.models.schemas import Category


class FileAnalysis(BaseModel):
    relative_path: str
    category: Category
    subcategory: str
    action: Literal[
        "move",
        "keep",
        "review"
    ]
    destination: str | None = None
    confidence: float = Field(
        ge=0.0,
        le=1.0
    )
    reason: str


class CleanupPlan(BaseModel):
    analyses: list[FileAnalysis]