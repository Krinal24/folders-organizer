import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    """Keep every test away from the real %LOCALAPPDATA%\\TidyByte."""
    folder = tmp_path_factory.mktemp("tidybyte-data")
    monkeypatch.setenv("TIDYBYTE_DATA_DIR", str(folder))
    monkeypatch.delenv("AI_READ_CONTENTS", raising=False)
    return folder
