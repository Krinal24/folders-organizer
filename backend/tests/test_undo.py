import json
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.executor import recycle_bin
from app.executor.executor import AlreadyUndone, get_run, list_runs, undo
from app.main import app
from tests.test_executor import op, run, write

REAL_ITEMS = recycle_bin._items  # Saved before conftest swaps in an empty bin.


class FakeBin:
    """Moves items into a folder and keeps records like a real bin does."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.folder.mkdir()
        self.items = []

    def __call__(self, path):
        data = self.folder / f"R{len(self.items)}"
        record = self.folder / f"I{len(self.items)}"
        shutil.move(path, data)
        record.write_text(path, encoding="utf-8")
        self.items.append(recycle_bin.Trashed(path, time.time(), data, record))

    def contents(self, original):
        return (item for item in self.items if item.record.exists())

    def empty(self):
        for item in self.items:
            if item.data.is_dir():
                shutil.rmtree(item.data)
            elif item.data.exists():
                item.data.unlink()
            item.record.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def journals(tmp_path, monkeypatch):
    monkeypatch.setenv("JOURNAL_DIR", str(tmp_path / "journals"))


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "Desktop"
    folder.mkdir()
    return folder


@pytest.fixture
def bin_(tmp_path, monkeypatch):
    fake = FakeBin(tmp_path / "bin")
    monkeypatch.setattr(recycle_bin, "_items", fake.contents)
    return fake


def three_changes(root, bin_):
    write(root / "cv.pdf")
    write(root / "song.mp3")
    write(root / "dup.pdf", b"copy")
    _, done = run(root, [
        op(root, "cv.pdf", "move", "Documents/Resumes"),
        op(root, "song.mp3", "move", "Music"),
        op(root, "dup.pdf", "delete"),
    ], trash=bin_)
    entries = get_run(done["journal_id"])["entries"]
    index = {entry.get("from") or entry["path"]: i for i, entry in enumerate(entries)}
    return done["journal_id"], index


# --- Per-file undo -----------------------------------------------------------

def test_undo_one_file_leaves_the_rest(root, bin_):
    run_id, index = three_changes(root, bin_)

    result = undo(run_id, [index["cv.pdf"]])

    assert (result["restored"], result["recovered"]) == (1, 0)
    assert (root / "cv.pdf").exists() and not (root / "Documents").exists()
    assert (root / "Music" / "song.mp3").exists() and not (root / "dup.pdf").exists()

    [summary] = list_runs()
    assert (summary["undone"], summary["pending"], summary["can_undo"]) == (1, 2, True)
    entries = get_run(run_id)["entries"]
    assert entries[index["cv.pdf"]]["undone"] and not entries[index["song.mp3"]].get("undone")

    # Later, the rest; what was already undone is skipped.
    result = undo(run_id)
    assert (result["restored"], result["recovered"], result["problems"]) == (1, 1, [])
    assert (root / "song.mp3").exists() and (root / "dup.pdf").read_bytes() == b"copy"
    assert not (root / "Music").exists()
    assert list_runs()[0]["can_undo"] is False
    with pytest.raises(AlreadyUndone):
        undo(run_id)


def test_undo_restores_a_deleted_file_from_the_bin(root, bin_):
    run_id, index = three_changes(root, bin_)

    result = undo(run_id, [index["dup.pdf"]])

    assert result["recovered"] == 1 and result["in_recycle_bin"] == 0
    assert (root / "dup.pdf").read_bytes() == b"copy"
    assert not bin_.items[0].record.exists()  # Gone from the bin.


def test_restores_a_deleted_empty_folder(root, bin_):
    (root / "old").mkdir()
    _, done = run(root, [op(root, "old", "delete", rule="empty_folder")], trash=bin_)

    assert undo(done["journal_id"])["recovered"] == 1
    assert (root / "old").is_dir()


def test_emptied_bin_is_reported_and_can_be_retried(root, bin_):
    run_id, index = three_changes(root, bin_)
    bin_.empty()

    result = undo(run_id, [index["dup.pdf"]])

    assert result["recovered"] == 0 and result["in_recycle_bin"] == 1
    assert "not in the Recycle Bin" in result["problems"][0]
    assert list_runs()[0]["pending"] == 3


def test_never_overwrites_something_put_back_in_its_place(root, bin_):
    run_id, index = three_changes(root, bin_)
    write(root / "dup.pdf", b"new")
    write(root / "cv.pdf", b"new")

    result = undo(run_id)

    assert result["restored"] == 1  # Only the song.
    assert len(result["problems"]) == 2
    assert all("something else is there now" in p for p in result["problems"])
    assert (root / "dup.pdf").read_bytes() == b"new"
    assert bin_.items[0].data.exists()  # Still safely in the bin.


def test_unsupported_platform_says_to_restore_by_hand(root, bin_, monkeypatch):
    run_id, index = three_changes(root, bin_)
    monkeypatch.setattr(recycle_bin, "supported", lambda: False)

    result = undo(run_id, [index["dup.pdf"]])

    assert "by hand" in result["problems"][0]


def test_rejects_unknown_entries(root, bin_):
    run_id, _ = three_changes(root, bin_)
    with pytest.raises(ValueError):
        undo(run_id, [7])

    client = TestClient(app)
    assert client.post("/api/undo", json={"journal_id": run_id, "entries": [-1]}).status_code == 400
    response = client.post("/api/undo", json={"journal_id": run_id, "entries": [0]})
    assert response.status_code == 200 and response.json()["restored"] + response.json()["recovered"] == 1


def test_created_folder_stays_while_other_files_are_in_it(root, bin_):
    write(root / "a.pdf")
    write(root / "b.pdf")
    _, done = run(root, [
        op(root, "a.pdf", "move", "Docs"),
        op(root, "b.pdf", "move", "Docs"),
    ], trash=bin_)

    undo(done["journal_id"], [0])
    assert (root / "Docs" / "b.pdf").exists()

    undo(done["journal_id"], [1])
    assert not (root / "Docs").exists()


def test_old_journals_keep_their_undone_moves_and_can_restore_deletes(root, bin_, tmp_path):
    write(root / "Docs" / "a.pdf")
    bin_(str(write(root / "b.pdf", b"old").resolve()))
    created = bin_.items[0].deleted_at - 1
    journal = {
        "root": str(root.resolve()),
        "created": created,
        "finished": created + 2,
        "completed": True,
        "entries": [
            {"op": "move", "from": "a.pdf", "to": "Docs/a.pdf"},
            {"op": "delete", "path": "b.pdf", "size": 3},  # No deleted_at back then.
        ],
        "created_dirs": [],
        "undone": {"at": created + 5, "restored": 1, "problems": []},
    }
    folder = tmp_path / "journals"
    folder.mkdir()
    (folder / "20260101-000000-old.json").write_text(json.dumps(journal), encoding="utf-8")

    [summary] = list_runs()
    assert (summary["undone"], summary["pending"]) == (1, 1)

    result = undo("20260101-000000-old")
    assert (result["restored"], result["recovered"]) == (0, 1)
    assert (root / "b.pdf").read_bytes() == b"old"


# --- Reading the bin's records -----------------------------------------------

def windows_record(path: str, deleted_at: float, version=2) -> bytes:
    filetime = int((deleted_at + recycle_bin.FILETIME_EPOCH) * 10_000_000)
    header = struct.pack("<qqq", version, 123, filetime)
    if version == 1:
        return header + path.encode("utf-16-le").ljust(520, b"\x00")
    text = path + "\x00"
    return header + struct.pack("<i", len(text)) + text.encode("utf-16-le")


@pytest.mark.parametrize("version", [1, 2])
def test_parses_windows_records(version):
    raw = windows_record(r"C:\Users\me\Desktop\cv (1).pdf", 1_700_000_000.5, version)

    path, deleted = recycle_bin.parse_windows_record(raw)

    assert path == r"C:\Users\me\Desktop\cv (1).pdf"
    assert deleted == pytest.approx(1_700_000_000.5, abs=0.001)


def test_ignores_damaged_windows_records():
    assert recycle_bin.parse_windows_record(b"\x02\x00") is None
    assert recycle_bin.parse_windows_record(struct.pack("<qqq", 9, 0, 0)) is None


def test_parses_linux_trashinfo():
    text = "[Trash Info]\nPath=/home/me/My%20Files/cv.pdf\nDeletionDate=2026-11-20T10:15:30\n"

    path, deleted = recycle_bin.parse_trashinfo(text)

    assert path == "/home/me/My Files/cv.pdf"
    assert deleted == time.mktime((2026, 11, 20, 10, 15, 30, 0, 0, -1))
    assert recycle_bin.parse_trashinfo("[Trash Info]\nPath=/x\n") is None


def test_find_picks_the_item_deleted_closest_to_our_record(tmp_path, monkeypatch):
    original = tmp_path / "cv.pdf"
    items = []
    for name, when in [("early", 1000.0), ("ours", 5000.0), ("other", 5001.0)]:
        data = write(tmp_path / name)
        path = str(original) if name != "other" else str(tmp_path / "x.pdf")
        items.append(recycle_bin.Trashed(path, when, data, data))
    monkeypatch.setattr(recycle_bin, "_items", lambda original: iter(items))

    assert recycle_bin.find(original, 5000.4, 0, 0).data.name == "ours"
    assert recycle_bin.find(original, 9000.0, 0, 0) is None
    # Older journals: anything from that path within the run's time span.
    assert recycle_bin.find(original, None, earliest=4990, latest=5010).data.name == "ours"


# --- The real Recycle Bin / Trash ------------------------------------------------

@pytest.mark.skipif(
    os.getenv("TIDYBYTE_REAL_BIN_TEST") != "1" or not recycle_bin.supported(),
    reason="Touches the real Recycle Bin; CI sets TIDYBYTE_REAL_BIN_TEST=1",
)
def test_round_trip_through_the_real_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(recycle_bin, "_items", REAL_ITEMS)
    # On Linux, files outside the home drive go to a different trash.
    base = Path.home() if sys.platform.startswith("linux") else tmp_path
    root = Path(tempfile.mkdtemp(prefix="tidybyte-bin-test-", dir=base))
    try:
        name = f"tidybyte-test-{time.time_ns()}.txt"
        write(root / name, b"restore me")

        _, done = run(root, [op(root, name, "delete")], trash=__import__("send2trash").send2trash)
        assert not (root / name).exists()

        result = undo(done["journal_id"])

        assert result["problems"] == [] and result["recovered"] == 1
        assert (root / name).read_bytes() == b"restore me"
    finally:
        shutil.rmtree(root, ignore_errors=True)
