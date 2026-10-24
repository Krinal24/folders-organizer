import os
import time

from app.rules.rules import DAY, apply_rules
from app.scanner.scanner import scan_folder


def write(path, content=b"x", age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if age_days:
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))


def run(tmp_path):
    scan = scan_folder(str(tmp_path))
    return {s["relative_path"]: s for s in apply_rules(tmp_path, scan)}


def test_duplicate_keeps_unmarked_original(tmp_path):
    write(tmp_path / "report (1).pdf", b"same content")
    write(tmp_path / "report.pdf", b"same content", age_days=2)

    result = run(tmp_path)

    assert list(result) == ["report (1).pdf"]
    assert result["report (1).pdf"]["rule"] == "duplicate"
    assert result["report (1).pdf"]["duplicate_of"] == "report.pdf"


def test_same_size_different_content_is_not_duplicate(tmp_path):
    write(tmp_path / "a.txt", b"aaaa")
    write(tmp_path / "a (1).txt", b"bbbb")

    assert run(tmp_path) == {}


def test_large_duplicates_need_full_hash(tmp_path):
    head = b"h" * (64 * 1024)
    write(tmp_path / "big.bin", head + b"tail-one")
    write(tmp_path / "big2.bin", head + b"tail-two")
    write(tmp_path / "big3.bin", head + b"tail-one")

    result = run(tmp_path)

    assert list(result) == ["big3.bin"]
    assert result["big3.bin"]["duplicate_of"] == "big.bin"


def test_partial_download_only_when_stale(tmp_path):
    write(tmp_path / "old.crdownload", b"old", age_days=3)
    write(tmp_path / "active.crdownload", b"active")
    write(tmp_path / "~$report.docx", b"lock", age_days=3)

    result = run(tmp_path)

    assert set(result) == {"old.crdownload", "~$report.docx"}
    assert all(s["rule"] == "partial_download" for s in result.values())


def test_old_installer_and_empty_file(tmp_path):
    write(tmp_path / "setup.msi", b"installer", age_days=45)
    write(tmp_path / "new_setup.exe", b"installer2")
    write(tmp_path / "empty.txt", b"")

    result = run(tmp_path)

    assert result["setup.msi"]["rule"] == "old_installer"
    assert result["empty.txt"]["rule"] == "empty_file"
    assert "new_setup.exe" not in result


def test_duplicate_wins_over_old_installer(tmp_path):
    write(tmp_path / "setup.exe", b"installer", age_days=60)
    write(tmp_path / "setup (1).exe", b"installer", age_days=45)

    result = run(tmp_path)

    assert result["setup (1).exe"]["rule"] == "duplicate"
    assert result["setup.exe"]["rule"] == "old_installer"


def test_empty_folder(tmp_path):
    (tmp_path / "nothing").mkdir()
    write(tmp_path / "full" / "file.txt")

    result = run(tmp_path)

    assert list(result) == ["nothing"]
    assert result["nothing"]["kind"] == "folder"
