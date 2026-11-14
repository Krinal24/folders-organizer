"""Near-duplicate photos: the same picture resized, re-compressed or
forwarded (e.g. through WhatsApp), which byte hashes miss.

Each image gets two difference hashes (dHash): shrink to grayscale and
record, for each pixel, whether it is brighter than its right-hand
neighbour. A coarse 8x8 hash finds candidates cheaply; a fine 16x16 hash
must agree too, because the coarse one alone can't tell apart screenshots
of the same app with different text.

Thresholds measured on real photos and edited copies of them:
  same photo  coarse <= 5 for resize, re-save, brightness; fine <= 21
  different   coarse >= 8 (look-alike screenshots), fine >= 60
Heavy crops (fine up to ~55) are deliberately not matched.
"""
import io
import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.storage import data_dir, write_json


# Formats Pillow reads without extra plugins.
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".gif", ".tiff"}

# Skip anything bigger: decoding it would take too long for a fingerprint.
MAX_PHOTO_SIZE = 50 * 1024 * 1024

# Comparing every pair is quadratic; beyond this, only the first ones count.
MAX_PHOTOS = 5000

COARSE_MAX = 5
FINE_MAX = 24

THUMBNAIL_SIZE = 160

logging.getLogger("PIL").setLevel(logging.WARNING)


def _dhash(gray: Image.Image, size: int) -> int:
    pixels = gray.resize((size + 1, size), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(size):
        for column in range(size):
            left = pixels[row * (size + 1) + column]
            right = pixels[row * (size + 1) + column + 1]
            bits = (bits << 1) | (left > right)
    return bits


def fingerprint(path: Path) -> dict[str, Any] | None:
    """Coarse and fine hashes plus dimensions, or None if unreadable."""
    try:
        with Image.open(path) as image:
            width, height = ImageOps.exif_transpose(image).size
            image.draft("L", (256, 256))  # JPEG: decode at reduced size, much faster.
            gray = ImageOps.exif_transpose(image).convert("L")
            return {
                "coarse": _dhash(gray, 8),
                "fine": _dhash(gray, 16),
                "width": width,
                "height": height,
            }
    except Exception:
        return None  # Corrupt, unsupported or not really an image.


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def same_photo(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        distance(a["coarse"], b["coarse"]) <= COARSE_MAX
        and distance(a["fine"], b["fine"]) <= FINE_MAX
    )


def is_candidate(item: dict[str, Any]) -> bool:
    return (
        item["kind"] == "file"
        and item["category"] == "images"
        and item["extension"] in PHOTO_SUFFIXES
        and 0 < item["size"] <= MAX_PHOTO_SIZE
        and not item.get("cloud_only")  # Reading it would trigger a download.
    )


# --- Cache: hashing is the slow part, and photos rarely change --------------

def _cache_file() -> Path:
    return data_dir() / "photo_hashes.json"


def _load_cache() -> dict[str, Any]:
    try:
        return json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fingerprints(root: Path, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """relative_path -> fingerprint, for every readable photo."""
    cache = _load_cache()
    changed = False
    result = {}

    for item in items[:MAX_PHOTOS]:
        path = root / item["relative_path"]
        key = str(path.resolve()).lower()
        stamp = [item["size"], item["modified"]]

        entry = cache.get(key)
        if entry is None or entry.get("stamp") != stamp:
            entry = {"stamp": stamp, "print": fingerprint(path)}
            cache[key] = entry
            changed = True

        if entry["print"] is not None:
            result[item["relative_path"]] = entry["print"]

    if changed:
        write_json(_cache_file(), cache)
    return result


def similar_groups(root: Path, items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Groups (2+) of items that look like the same photo."""
    candidates = [item for item in items if is_candidate(item)]
    prints = fingerprints(root, candidates)
    photos = [item for item in candidates if item["relative_path"] in prints]

    # Union-find over every matching pair.
    parent = list(range(len(photos)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(photos):
        for j in range(i + 1, len(photos)):
            if same_photo(prints[a["relative_path"]], prints[photos[j]["relative_path"]]):
                parent[find(i)] = find(j)

    groups = {}
    for i, photo in enumerate(photos):
        groups.setdefault(find(i), []).append(
            {**photo, **{k: prints[photo["relative_path"]][k] for k in ("width", "height")}}
        )
    return [group for group in groups.values() if len(group) > 1]


def thumbnail(path: Path) -> bytes:
    with Image.open(path) as image:
        image.draft("RGB", (THUMBNAIL_SIZE * 2, THUMBNAIL_SIZE * 2))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return buffer.getvalue()
