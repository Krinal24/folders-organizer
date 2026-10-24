import pytest

from app.ai.analyzer import AIAnalyzer, is_safe_destination
from app.models.ai_schemas import CleanupPlan, FileAnalysis
from app.planner import build_plan


class FakeAnalyzer(AIAnalyzer):
    def __init__(self, destination="Documents/Notes"):
        self.destination = destination
        self.received = None

    def analyze(self, files):
        self.received = files
        return CleanupPlan(analyses=[
            FileAnalysis(
                relative_path=file["relative_path"],
                category=file["category"],
                subcategory="notes",
                action="move",
                destination=self.destination,
                confidence=0.8,
                reason="Looks like notes.",
            )
            for file in files
        ] + [
            FileAnalysis(
                relative_path="invented.txt",
                category="documents",
                subcategory="other",
                action="keep",
                confidence=0.5,
                reason="Hallucinated.",
            )
        ])


class BrokenAnalyzer(AIAnalyzer):
    def analyze(self, files):
        raise ConnectionError("Ollama is not running")


@pytest.mark.parametrize("destination, safe", [
    ("Documents/Resumes", True),
    ("Images", True),
    (r"C:\Windows", False),
    ("D:stuff", False),
    ("/etc", False),
    (r"\Users", False),
    (r"..\..\System32", False),
    ("Docs/../../x", False),
    ("  ", False),
])
def test_is_safe_destination(destination, safe):
    assert is_safe_destination(destination) is safe


def make_folder(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"notes")
    (tmp_path / "notes (1).txt").write_bytes(b"notes")


def test_rules_handle_files_before_ai(tmp_path):
    make_folder(tmp_path)
    fake = FakeAnalyzer()

    result = build_plan(str(tmp_path), analyzer_factory=lambda: fake)

    assert [f["relative_path"] for f in fake.received] == ["notes.txt"]
    by_path = {s["relative_path"]: s for s in result["suggestions"]}
    assert by_path["notes (1).txt"]["source"] == "rule"
    assert by_path["notes.txt"]["source"] == "ai"
    assert "invented.txt" not in by_path
    assert result["reclaimable_size"] == 5
    assert result["ai_used"] is True


def test_unsafe_ai_destination_becomes_review(tmp_path):
    make_folder(tmp_path)

    result = build_plan(
        str(tmp_path),
        analyzer_factory=lambda: FakeAnalyzer(destination=r"C:\Windows"),
    )

    ai = next(s for s in result["suggestions"] if s["source"] == "ai")
    assert ai["action"] == "review"
    assert ai["destination"] is None


def test_ai_failure_still_returns_rule_results(tmp_path):
    make_folder(tmp_path)

    result = build_plan(str(tmp_path), analyzer_factory=BrokenAnalyzer)

    assert result["ai_used"] is False
    assert "Ollama is not running" in result["ai_error"]
    assert [s["source"] for s in result["suggestions"]] == ["rule"]


def test_use_ai_false_skips_ai(tmp_path):
    make_folder(tmp_path)

    def explode():
        raise AssertionError("AI should not be called")

    result = build_plan(str(tmp_path), use_ai=False, analyzer_factory=explode)

    assert result["ai_used"] is False
    assert result["ai_error"] is None
