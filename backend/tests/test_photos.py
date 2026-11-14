import io
import os
import random

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api import routes
from app.main import app
from app.rules.photos import fingerprint, same_photo
from app.rules.rules import apply_rules
from app.scanner.scanner import scan_folder


def make_photo(path, seed, size=(800, 600)):
    """A photo-like image: soft background plus random shapes."""
    rng = random.Random(seed)
    image = Image.new("RGB", size, tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(image)
    for _ in range(25):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        r = rng.randrange(20, 160)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=tuple(rng.randrange(256) for _ in range(3)))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=92)
    return image


def test_resized_and_recompressed_copies_match_but_different_photos_dont(tmp_path):
    original = make_photo(tmp_path / "beach.jpg", seed=1)
    original.resize((400, 300)).save(tmp_path / "beach small.jpg", quality=60)
    original.save(tmp_path / "beach.png")
    make_photo(tmp_path / "mountain.jpg", seed=2)

    prints = {name: fingerprint(tmp_path / name) for name in ("beach.jpg", "beach small.jpg", "beach.png", "mountain.jpg")}

    assert same_photo(prints["beach.jpg"], prints["beach small.jpg"])
    assert same_photo(prints["beach.jpg"], prints["beach.png"])
    assert not same_photo(prints["beach.jpg"], prints["mountain.jpg"])
    assert prints["beach.jpg"]["width"] == 800


def test_rules_keep_the_sharpest_copy(tmp_path):
    original = make_photo(tmp_path / "IMG_2041.jpg", seed=3, size=(1200, 900))
    original.resize((600, 450)).save(tmp_path / "WhatsApp Image 2024.jpeg", quality=70)
    make_photo(tmp_path / "other.jpg", seed=4)
    (tmp_path / "broken.jpg").write_bytes(b"not an image")

    suggestions = apply_rules(tmp_path, scan_folder(str(tmp_path)))
    similar = [s for s in suggestions if s["rule"] == "similar_photo"]

    assert len(similar) == 1
    assert similar[0]["relative_path"] == "WhatsApp Image 2024.jpeg"
    assert similar[0]["duplicate_of"] == "IMG_2041.jpg"
    assert "600×450 here vs 1200×900 kept" in similar[0]["reason"]
    assert similar[0]["action"] == "delete"


def test_exact_duplicates_are_still_reported_as_duplicates(tmp_path):
    make_photo(tmp_path / "a.jpg", seed=5)
    (tmp_path / "a (1).jpg").write_bytes((tmp_path / "a.jpg").read_bytes())

    rules = {s["relative_path"]: s["rule"] for s in apply_rules(tmp_path, scan_folder(str(tmp_path)))}

    assert rules["a (1).jpg"] == "duplicate"


def test_fingerprints_are_cached(tmp_path, monkeypatch):
    make_photo(tmp_path / "a.jpg", seed=6)
    make_photo(tmp_path / "b.jpg", seed=7)
    apply_rules(tmp_path, scan_folder(str(tmp_path)))

    calls = []
    import app.rules.photos as photos
    monkeypatch.setattr(photos, "fingerprint", lambda path: calls.append(path))
    apply_rules(tmp_path, scan_folder(str(tmp_path)))

    assert calls == []


def test_thumbnails_only_from_scanned_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "scanned_roots", set())
    make_photo(tmp_path / "Pics" / "a.jpg", seed=8)
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path.parent / "outside.jpg").write_bytes((tmp_path / "Pics" / "a.jpg").read_bytes())
    client = TestClient(app)

    def get(path):
        return client.get("/api/thumbnail", params={"root": str(tmp_path), "path": path})

    assert get(os.path.join("Pics", "a.jpg")).status_code == 403  # Not scanned yet.

    client.post("/api/scan", json={"path": str(tmp_path)})
    ok = get(os.path.join("Pics", "a.jpg"))
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(ok.content)).size) <= 160

    assert get(os.path.join("..", "outside.jpg")).status_code == 403
    assert get("notes.txt").status_code == 404
