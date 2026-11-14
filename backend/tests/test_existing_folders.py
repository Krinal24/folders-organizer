import os

import pytest

from app.ai.analyzer import AIAnalyzer
from app.learning import store
from app.models.ai_schemas import FileAnalysis
from app.planner import stream_plan
from app.rules.folders import adopt_existing, existing_folders, find_existing
from app.scanner.scanner import scan_folder


def write(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


FOLDERS = ["RESUMES", "Documents", "Documents/CV", "My Pictures", "Movies", "Study stuff"]


@pytest.mark.parametrize("destination, expected", [
    ("Documents/Resumes", "Documents/CV"),  # same parent wins
    ("Resumes", "RESUMES"),
    # Only whole names match: "My Pictures" is not a "Pictures" folder.
    ("Images/Photos", None),
    ("Videos", "Movies"),
    ("documents", "Documents"),
    ("Documents/Study", None),
    ("Music", None),
])
def test_find_existing(destination, expected):
    assert find_existing(destination, FOLDERS) == expected


def test_plural_and_case_insensitive():
    assert find_existing("Documents/Resumes", ["Resume"]) == "Resume"
    assert find_existing("Images/Screenshots", ["screenshot"]) == "screenshot"
    assert find_existing("Images/Photos", ["Pictures"]) == "Pictures"


def test_existing_folders_from_scan(tmp_path):
    write(tmp_path / "RESUMES" / "old.pdf")
    write(tmp_path / "College" / "Sem 3" / "Maths" / "notes.pdf")
    (tmp_path / "Empty Photos").mkdir()

    folders = existing_folders(scan_folder(str(tmp_path)))

    assert folders == ["College", "College/Sem 3", "Empty Photos", "RESUMES"]


def suggestion(path, destination, rule=None):
    return {
        "relative_path": path, "action": "move", "destination": destination,
        "reason": "Resume in name.", "rule": rule,
    }


def test_adopt_rewrites_moves_but_not_learned_rules():
    adopted = adopt_existing(suggestion("cv.pdf", "Documents/Resumes"), ["RESUMES"])
    assert adopted["destination"] == "RESUMES"
    assert adopted["reason"].endswith("Using your existing RESUMES folder.")

    learned = suggestion("cv.pdf", "Documents/Resumes", rule="learned")
    assert adopt_existing(learned, ["RESUMES"]) == learned


def test_adopt_keeps_files_already_in_the_existing_folder():
    adopted = adopt_existing(suggestion(os.path.join("RESUMES", "cv.pdf"), "Documents/Resumes"), ["RESUMES"])

    assert (adopted["action"], adopted["destination"]) == ("keep", None)


class ResumeAI(AIAnalyzer):
    def analyze(self, files):
        raise NotImplementedError

    def analyze_stream(self, files, examples=(), context=None):
        for file in files:
            yield FileAnalysis(
                relative_path=file["relative_path"], category="documents",
                subcategory="resumes", action="move",
                destination="Documents/Resumes", confidence=0.9, reason="Resume in name.",
            )


def test_planner_uses_the_users_folder(tmp_path):
    write(tmp_path / "Krinal_Resume_2026.pdf", b"a")
    write(tmp_path / "Krinal_CV_old.pdf", b"b")
    write(tmp_path / "trailer.mp4", b"c")
    write(tmp_path / "RESUMES" / "2024.pdf", b"d")
    write(tmp_path / "Movies" / "film.mkv", b"e")

    events = list(stream_plan(str(tmp_path), analyzer_factory=ResumeAI))

    rules_event, *ai_events = [e for e in events if e["type"] in ("rules", "ai")]
    video = rules_event["suggestions"][0]
    assert (video["relative_path"], video["destination"]) == ("trailer.mp4", "Movies")
    assert {e["suggestion"]["destination"] for e in ai_events} == {"RESUMES"}
    # The Change… menu offers the user's folders instead of the look-alikes.
    assert "RESUMES" in rules_event["destinations"]
    assert "Documents/Resumes" not in rules_event["destinations"]
    assert "Videos" not in rules_event["destinations"]


def test_learned_rule_destination_is_respected(tmp_path):
    write(tmp_path / "Krinal_Resume_2026.pdf")
    write(tmp_path / "RESUMES" / "2024.pdf")
    store.add_rule("Resume", "move", "Documents/Resumes")

    rules_event = next(stream_plan(str(tmp_path), use_ai=False))

    [suggestion] = rules_event["suggestions"]
    assert suggestion["destination"] == "Documents/Resumes"


def test_tidybyte_never_suggests_moving_itself(tmp_path, monkeypatch):
    import app.planner as planner

    write(tmp_path / "tidybyte" / "package.json", b"{}")
    write(tmp_path / "other-app" / "package.json", b"{}")
    monkeypatch.setattr(planner, "APP_DIR", (tmp_path / "tidybyte" / "backend").resolve())

    rules_event = next(stream_plan(str(tmp_path), use_ai=False))

    by_path = {s["relative_path"]: s for s in rules_event["suggestions"]}
    assert by_path["tidybyte"]["action"] == "keep"
    assert "runs from this folder" in by_path["tidybyte"]["reason"]
    assert by_path["other-app"]["destination"] == "Projects"
