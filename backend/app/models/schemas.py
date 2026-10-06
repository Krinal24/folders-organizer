from pydantic import BaseModel
from typing import Literal


class FileInfo(BaseModel):
    name: str
    extension: str
    category: str
    size: int


class ScanResult(BaseModel):
    path: str
    total: int
    documents: int
    images: int
    videos: int
    audio: int
    executables: int
    archives: int
    unknown: int
    files: list[FileInfo]


class ScanRequest(BaseModel):
    downloads_path: str


class HealthResponse(BaseModel):
    status: Literal["ok"]