import json
import os
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    """Where TidyByte keeps its own data: never inside the user's folders."""
    override = os.getenv("TIDYBYTE_DATA_DIR")
    if override:
        return Path(override)
    base = os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share"
    return Path(base) / "TidyByte"


def write_json(path: Path, data: Any) -> None:
    """Write then rename, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temporary, path)
