import json
import os

import pytest
from fastapi.testclient import TestClient

from app.executor.executor import execute_plan, undo
from app.main import app


@pytest.fixture(autouse=True)
def journals(tmp_path, monkeypatch):
    folder = tmp_path / "journals"
    monkeypatch.setenv("JOURNAL_DIR", str(folder))
    return folder


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


class FakeTrash:
    def __init__(self):
        self.trashed = []

    def __call__(self, path):
        self.trashed.append(path)
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)


def write(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def op(root, relative_path, action, destination=None, **extra):
    path = root / relative_path
    stats = path.stat() if path.exists() else None
    return {
        "relative_path": relative_path,
        "kind": "folder" if path.is_dir() else "file",
        "action": action,
        "destination": destination,
        "size": stats.st_size if stats and path.is_file() else None,
        "modified": stats.st_mtime if stats else None,
        **extra,
    }


def run(root, operations, trash=None):
    events = list(execute_plan(str(root), operations, trash=trash or FakeTrash()))
    results = {e["relative_path"]: e for e in events if e["type"] == "result"}
    return results, events[-1]


def test_moves_files_and_creates_folders(root):
    write(root / "cv.pdf")

    results, done = run(root, [op(root, "cv.pdf", "move", "Documents/Resumes")])

    assert results["cv.pdf"]["status"] == "done"
    assert (root / "Documents" / "Resumes" / "cv.pdf").exists()
    assert not (root / "cv.pdf").exists()
    assert done["done"] == 1 and done["journal_id"]


def test_name_clash_renames_instead_of_overwriting(root):
    write(root / "cv.pdf", b"new")
    write(root / "Documents" / "cv.pdf", b"old")

    results, _ = run(root, [op(root, "cv.pdf", "move", "Documents")])

    assert results["cv.pdf"]["new_path"] == os.path.join("Documents", "cv (1).pdf")
    assert (root / "Documents" / "cv.pdf").read_bytes() == b"old"
    assert (root / "Documents" / "cv (1).pdf").read_bytes() == b"new"


def test_delete_goes_to_trash_and_counts_freed_space(root):
    write(root / "copy (1).pdf", b"12345")
    trash = FakeTrash()

    results, done = run(root, [op(root, "copy (1).pdf", "delete")], trash)

    assert results["copy (1).pdf"]["status"] == "done"
    assert trash.trashed == [str((root / "copy (1).pdf").resolve())]
    assert done["freed"] == 5


def test_changed_file_is_skipped(root):
    write(root / "notes.pdf", b"v1")
    operation = op(root, "notes.pdf", "delete")
    write(root / "notes.pdf", b"version two")

    results, _ = run(root, [operation])

    assert results["notes.pdf"]["status"] == "skipped"
    assert "Changed" in results["notes.pdf"]["detail"]
    assert (root / "notes.pdf").exists()


@pytest.mark.parametrize("relative_path, destination", [
    (os.path.join("..", "outside.txt"), "Docs"),
    ("inside.txt", r"C:\Windows"),
    ("inside.txt", os.path.join("..", "escape")),
])
def test_paths_outside_the_folder_are_refused(root, relative_path, destination):
    write(root.parent / "outside.txt")
    write(root / "inside.txt")

    operation = {
        "relative_path": relative_path, "kind": "file", "action": "move",
        "destination": destination,
    }
    results, _ = run(root, [operation])

    assert results[relative_path]["status"] == "skipped"
    assert (root.parent / "outside.txt").exists()
    assert (root / "inside.txt").exists()


def test_missing_and_already_in_place(root):
    write(root / "Videos" / "clip.mp4")

    results, _ = run(root, [
        {"relative_path": "gone.pdf", "action": "delete"},
        op(root, os.path.join("Videos", "clip.mp4"), "move", "Videos"),
    ])

    assert results["gone.pdf"]["detail"] == "No longer exists."
    assert results[os.path.join("Videos", "clip.mp4")]["detail"] == "Already in that folder."


def test_empty_folder_delete_runs_last_and_never_deletes_contents(root):
    (root / "empty").mkdir()
    (root / "filled").mkdir()
    operations = [
        op(root, "empty", "delete", rule="empty_folder"),
        op(root, "filled", "delete", rule="empty_folder"),
    ]
    # Something lands in "filled" after the analysis, keeping its mtime.
    stamp = (root / "filled").stat().st_mtime
    write(root / "filled" / "new.pdf")
    os.utime(root / "filled", (stamp, stamp))

    results, _ = run(root, operations)

    assert results["empty"]["status"] == "done"
    assert results["filled"]["detail"] == "Folder is no longer empty."
    assert (root / "filled" / "new.pdf").exists()


def test_folder_deletes_run_after_file_moves(root):
    write(root / "a.pdf")
    (root / "empty").mkdir()

    events = list(execute_plan(str(root), [
        op(root, "empty", "delete", rule="empty_folder"),
        op(root, "a.pdf", "move", "Docs"),
    ], trash=FakeTrash()))

    order = [e["relative_path"] for e in events if e["type"] == "result"]
    assert order == ["a.pdf", "empty"]


def test_undo_restores_moves_and_removes_created_folders(root):
    write(root / "cv.pdf")
    write(root / "song.mp3")
    write(root / "dup.pdf")

    _, done = run(root, [
        op(root, "cv.pdf", "move", "Documents/Resumes"),
        op(root, "song.mp3", "move", "Music"),
        op(root, "dup.pdf", "delete"),
    ])
    summary = undo(done["journal_id"])

    assert summary["restored"] == 2
    assert summary["in_recycle_bin"] == 1
    assert (root / "cv.pdf").exists() and (root / "song.mp3").exists()
    assert not (root / "Documents").exists() and not (root / "Music").exists()

    with pytest.raises(FileNotFoundError):
        undo(done["journal_id"])


def test_stopped_run_can_still_be_undone(root):
    write(root / "a.pdf")
    write(root / "b.pdf")
    events = execute_plan(str(root), [
        op(root, "a.pdf", "move", "Docs"),
        op(root, "b.pdf", "move", "Docs"),
    ], trash=FakeTrash())

    started = next(events)
    next(events)  # First move done; then the client disconnects.
    events.close()

    assert undo(started["journal_id"])["restored"] == 1
    assert (root / "a.pdf").exists()
    assert not (root / "Docs").exists()


def test_undo_rejects_bad_ids():
    with pytest.raises(ValueError):
        undo("../../etc/passwd")


def test_execute_endpoint_streams_results(root, monkeypatch):
    write(root / "cv.pdf")
    operation = op(root, "cv.pdf", "move", "Documents")

    response = TestClient(app).post(
        "/api/execute", json={"path": str(root), "operations": [operation]}
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [e["type"] for e in events] == ["started", "result", "done"]
    assert (root / "Documents" / "cv.pdf").exists()


def test_execute_endpoint_rejects_missing_folder(tmp_path):
    response = TestClient(app).post(
        "/api/execute", json={"path": str(tmp_path / "nope"), "operations": []}
    )

    assert response.status_code == 404


def test_execute_endpoint_rejects_unknown_actions(root):
    response = TestClient(app).post("/api/execute", json={
        "path": str(root),
        "operations": [{"relative_path": "x", "action": "chmod"}],
    })

    assert response.status_code == 422
