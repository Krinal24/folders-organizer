from pathlib import Path
from collections import Counter
from typing import Any


FILE_CATEGORIES = {
    "documents": {
        ".pdf", ".doc", ".docx", ".txt", ".rtf",
        ".xls", ".xlsx", ".csv", ".ppt", ".pptx",
        ".odt", ".ods", ".odp"
    },
    "images": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp",
        ".webp", ".svg", ".tiff", ".ico"
    },
    "videos": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv",
        ".flv", ".webm", ".m4v"
    },
    "audio": {
        ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"
    },
    "executables": {
        ".exe", ".msi", ".bat", ".cmd", ".com", ".scr"
    },
    "archives": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"
    }
}


def get_file_category(file_path: Path) -> str:
    extension = file_path.suffix.lower()

    for category, extensions in FILE_CATEGORIES.items():
        if extension in extensions:
            return category

    return "unknown"


def scan_downloads(downloads_path: str) -> dict[str, Any]:
    path = Path(downloads_path).expanduser()

    if not path.exists():
        raise FileNotFoundError(f"Downloads folder not found: {path}")

    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    files = [
        file
        for file in path.rglob("*")
        if file.is_file()
    ]

    counts = Counter()

    file_details = []

    for file in files:
        category = get_file_category(file)
        counts[category] += 1

        file_details.append({
            "name": file.name,
            "relative_path": str(file.relative_to(path)),
            "extension": file.suffix.lower(),
            "category": category,
            "size": file.stat().st_size
        })

    return {
        "path": str(path),
        "total": len(files),
        "documents": counts["documents"],
        "images": counts["images"],
        "videos": counts["videos"],
        "audio": counts["audio"],
        "executables": counts["executables"],
        "archives": counts["archives"],
        "unknown": counts["unknown"],
        "files": file_details
    }