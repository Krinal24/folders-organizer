import os

from app.ai.analyzer import AIAnalyzer
from app.models.ai_schemas import FileAnalysis
from app.planner import stream_plan
from app.scanner.scanner import scan_folder


def write(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class RecordingAnalyzer(AIAnalyzer):
    def __init__(self):
        self.files, self.context = [], None

    def analyze(self, files):
        raise NotImplementedError

    def analyze_stream(self, files, examples=(), context=None):
        self.files, self.context = files, context
        for file in files:
            yield FileAnalysis(
                relative_path=file["relative_path"], category="documents",
                subcategory="other", action="keep", confidence=0.5, reason="ok",
            )


def make_desktop(root):
    write(root / "invoice.pdf", b"loose")
    write(root / "song.mp3", b"song")
    (root / "empty top").mkdir()
    write(root / "College" / "notes.pdf", b"notes")
    write(root / "College" / "lecture.mp4", b"video")
    (root / "College" / "empty inside").mkdir()


def test_only_loose_files_by_default(tmp_path):
    make_desktop(tmp_path)
    analyzer = RecordingAnalyzer()

    events = list(stream_plan(str(tmp_path), analyzer_factory=lambda: analyzer))

    rules = events[0]
    assert {s["relative_path"] for s in rules["suggestions"]} == {"song.mp3", "empty top"}
    assert [f["name"] for f in analyzer.files] == ["invoice.pdf"]
    assert rules["left_alone"] == {"files": 2, "folders": 1}
    # Existing folders are still offered, to the user and to the AI.
    assert "College" in rules["destinations"]
    assert any(item["relative_path"].startswith("College") for item in analyzer.context)


def test_subfolders_included_on_request(tmp_path):
    make_desktop(tmp_path)
    analyzer = RecordingAnalyzer()

    events = list(stream_plan(
        str(tmp_path), analyzer_factory=lambda: analyzer, include_subfolders=True
    ))

    paths = {s["relative_path"] for s in events[0]["suggestions"]}
    assert os.path.join("College", "lecture.mp4") in paths
    assert os.path.join("College", "empty inside") in paths
    assert {f["name"] for f in analyzer.files} == {"invoice.pdf", "notes.pdf"}
    assert events[0]["left_alone"] is None


def test_datasets_and_notebook_folders_are_kept_whole(tmp_path):
    for n in range(60):
        write(tmp_path / "upGrad" / "data" / f"img_{n}.jpg")
        write(tmp_path / "upGrad" / "data" / f"img_{n}.xml")
    write(tmp_path / "upGrad" / "data" / "readme.txt")
    write(tmp_path / "ML course" / "week1.ipynb")
    write(tmp_path / "ML course" / "train.csv")
    write(tmp_path / "Mixed" / "a.pdf")

    items = {i["relative_path"]: i for i in scan_folder(str(tmp_path))["items"]}

    dataset = items[os.path.join("upGrad", "data")]
    assert (dataset["kind"], dataset["category"], dataset["file_count"]) == ("folder", "datasets", 121)
    assert items["ML course"]["category"] == "projects"
    assert os.path.join("Mixed", "a.pdf") in items
