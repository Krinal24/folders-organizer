import subprocess

from fastapi.testclient import TestClient

from app import picker
from app.main import app


def fake_run(stdout="", returncode=0, error=None):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if error:
            raise error
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return run, calls


def test_returns_windows_style_path(monkeypatch, tmp_path):
    run, calls = fake_run(stdout=tmp_path.as_posix())
    monkeypatch.setattr(picker.subprocess, "run", run)

    assert picker.pick_folder(str(tmp_path)) == str(tmp_path)
    # Starts where the user already was.
    assert calls[0][-1] == str(tmp_path)


def test_cancel_and_timeout_give_none(monkeypatch):
    run, _ = fake_run(stdout="")
    monkeypatch.setattr(picker.subprocess, "run", run)
    assert picker.pick_folder() is None

    run, _ = fake_run(error=subprocess.TimeoutExpired("python", 600))
    monkeypatch.setattr(picker.subprocess, "run", run)
    assert picker.pick_folder() is None


def test_missing_initial_folder_is_ignored(monkeypatch, tmp_path):
    run, calls = fake_run()
    monkeypatch.setattr(picker.subprocess, "run", run)

    picker.pick_folder(str(tmp_path / "gone"))

    assert calls[0][-1] == ""


def test_endpoint(monkeypatch, tmp_path):
    run, _ = fake_run(stdout=tmp_path.as_posix())
    monkeypatch.setattr(picker.subprocess, "run", run)
    client = TestClient(app)

    assert client.post("/api/pick-folder", json={}).json() == {"path": str(tmp_path)}

    run, _ = fake_run(returncode=1)
    monkeypatch.setattr(picker.subprocess, "run", run)
    assert client.post("/api/pick-folder", json={}).status_code == 501
