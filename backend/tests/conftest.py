import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    """Keep every test away from the real %LOCALAPPDATA%\\TidyByte."""
    folder = tmp_path_factory.mktemp("tidybyte-data")
    monkeypatch.setenv("TIDYBYTE_DATA_DIR", str(folder))
    monkeypatch.delenv("AI_READ_CONTENTS", raising=False)
    return folder


@pytest.fixture(autouse=True)
def empty_recycle_bin(monkeypatch):
    """Never read or restore from the real Recycle Bin in tests."""
    from app.executor import recycle_bin

    monkeypatch.setattr(recycle_bin, "_items", lambda original: iter(()))
    monkeypatch.setattr(recycle_bin, "supported", lambda: True)


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch):
    """OCR is slow and machine-dependent; tests opt in explicitly."""
    from app.content import ocr

    monkeypatch.setattr(ocr, "read_scanned_pdf", lambda path: "")


@pytest.fixture(autouse=True)
def no_session_key():
    """API tests skip the session key; test_session.py checks it."""
    from app.main import app
    from app.security import require_session

    app.dependency_overrides[require_session] = lambda: None
    yield
    app.dependency_overrides.pop(require_session, None)
