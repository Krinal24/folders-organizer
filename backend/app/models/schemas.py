from pydantic import BaseModel
from typing import Literal


Category = Literal[
    "documents",
    "images",
    "videos",
    "audio",
    "executables",
    "archives",
    "projects",
    "unknown",
]


class ScannedItem(BaseModel):
    # "folder" items are self-contained bundles (git repos, code projects)
    # that must be moved as a unit, never split apart.
    kind: Literal["file", "folder"]
    name: str
    relative_path: str
    extension: str
    category: Category
    size: int
    modified: float
    file_count: int | None = None
    # OneDrive/cloud placeholder: reading its content would trigger a download.
    cloud_only: bool = False


class SkippedPath(BaseModel):
    relative_path: str
    reason: str


class ScanResult(BaseModel):
    path: str
    total_items: int
    total_files: int
    total_size: int
    counts: dict[str, int]
    sizes: dict[str, int]
    items: list[ScannedItem]
    skipped: list[SkippedPath]
    truncated: bool


class ScanRequest(BaseModel):
    path: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
