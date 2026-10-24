import json

from fastapi.testclient import TestClient

from app.ai.analyzer import AIAnalyzer
from app.main import app
from app.models.ai_schemas import FileAnalysis
from app.planner import stream_plan


def analysis(path):
    return FileAnalysis(
        relative_path=path,
        category="documents",
        subcategory="notes",
        action="keep",
        confidence=0.6,
        reason="Fine where it is.",
    )


class FailsMidway(AIAnalyzer):
    def analyze(self, files):
        raise NotImplementedError

    def analyze_stream(self, files):
        yield analysis(files[0]["relative_path"])
        raise ConnectionError("Ollama went away")


def make_folder(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "b.txt").write_bytes(b"bb")
    (tmp_path / "b (1).txt").write_bytes(b"bb")


def test_rules_event_arrives_before_ai_starts(tmp_path):
    make_folder(tmp_path)
    calls = []

    def factory():
        calls.append("ai")
        return FailsMidway()

    events = stream_plan(str(tmp_path), analyzer_factory=factory)
    first = next(events)

    assert first["type"] == "rules"
    assert first["ai_pending"] == 2
    assert "Documents/Study" in first["destinations"]
    assert "Videos" in first["destinations"]
    assert [s["relative_path"] for s in first["suggestions"]] == ["b (1).txt"]
    assert calls == []


def test_ai_failure_midway_keeps_earlier_results(tmp_path):
    make_folder(tmp_path)

    events = list(stream_plan(str(tmp_path), analyzer_factory=FailsMidway))

    assert [e["type"] for e in events] == ["rules", "ai", "error", "done"]
    assert "Ollama went away" in events[2]["message"]
    assert events[3]["ai_used"] is False


def test_endpoint_streams_ndjson(tmp_path):
    make_folder(tmp_path)

    response = TestClient(app).post(
        "/api/analyze", json={"path": str(tmp_path), "use_ai": False}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [e["type"] for e in events] == ["rules", "done"]


def test_endpoint_missing_folder_is_404(tmp_path):
    response = TestClient(app).post(
        "/api/analyze", json={"path": str(tmp_path / "nope"), "use_ai": False}
    )

    assert response.status_code == 404
