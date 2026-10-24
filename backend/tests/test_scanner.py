import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scanner.scanner import scan_folder


def write(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def by_path(result):
    return {item["relative_path"]: item for item in result["items"]}


def test_nested_files_keep_relative_path(tmp_path):
    write(tmp_path / "a.pdf")
    write(tmp_path / "Old" / "a.pdf")

    items = by_path(scan_folder(str(tmp_path)))

    assert set(items) == {"a.pdf", os.path.join("Old", "a.pdf")}


def test_totals_and_sizes(tmp_path):
    write(tmp_path / "doc.pdf", 100)
    write(tmp_path / "pic.heic", 50)
    write(tmp_path / "song.mp3", 25)

    result = scan_folder(str(tmp_path))

    assert result["total_size"] == 175
    assert result["total_files"] == 3
    assert result["counts"] == {"documents": 1, "images": 1, "audio": 1}
    assert result["sizes"]["documents"] == 100


def test_project_folder_is_one_unit(tmp_path):
    write(tmp_path / "myapp" / "package.json", 5)
    write(tmp_path / "myapp" / "src" / "index.js", 20)
    write(tmp_path / "myapp" / "logo.png", 30)

    result = scan_folder(str(tmp_path))
    items = by_path(result)

    assert list(items) == ["myapp"]
    project = items["myapp"]
    assert project["kind"] == "folder"
    assert project["category"] == "projects"
    assert project["size"] == 55
    assert project["file_count"] == 3
    assert result["total_files"] == 3


def test_excluded_dirs_and_files_are_ignored(tmp_path):
    write(tmp_path / "node_modules" / "lib.js")
    write(tmp_path / "desktop.ini")
    write(tmp_path / "keep.txt")

    assert list(by_path(scan_folder(str(tmp_path)))) == ["keep.txt"]


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_folder(str(tmp_path / "nope"))


def test_scan_endpoint_returns_relative_path(tmp_path):
    write(tmp_path / "sub" / "notes.txt")

    response = TestClient(app).post("/api/scan", json={"path": str(tmp_path)})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["relative_path"].endswith("notes.txt")
    assert item["relative_path"] != item["name"]
