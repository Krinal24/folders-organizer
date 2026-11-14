import os
import time

import pytest
from fastapi.testclient import TestClient

from app.ai.analyzer import AIAnalyzer
from app.ai.prompts import GROUPS, build_system_prompt, learned_folders, relevant_examples
from app.learning import store
from app.main import app
from app.models.ai_schemas import FileAnalysis
from app.planner import build_plan, stream_plan
from app.rules.rules import DAY, apply_rules
from app.scanner.scanner import scan_folder
from tests.test_batched import ScriptedAnalyzer, by_path, doc


def write(path, content=b"x", age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if age_days:
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))


def correction(name, destination, category="documents", action="move"):
    return {
        "relative_path": name,
        "category": category,
        "suggested_action": "move",
        "suggested_destination": "Documents/Other",
        "chosen_action": action,
        "chosen_destination": destination,
    }


def stored(*args, **kwargs):
    """A correction as the store keeps it: by file name."""
    item = correction(*args, **kwargs)
    item["name"] = os.path.basename(item.pop("relative_path"))
    return item


# --- Store --------------------------------------------------------------------

def test_rules_are_validated():
    with pytest.raises(store.InvalidRule):
        store.add_rule("x", "move", "Docs")
    with pytest.raises(store.InvalidRule):
        store.add_rule("21MAT", "move", r"C:\Windows")
    with pytest.raises(store.InvalidRule):
        store.add_rule("21MAT", "move", None)
    with pytest.raises(store.InvalidRule):
        store.add_rule("21MAT", "delete")

    rule = store.add_rule("  21MAT ", "move", "Documents\\Study\\")
    assert (rule["contains"], rule["destination"]) == ("21MAT", "Documents/Study")


def test_same_text_replaces_rule_and_delete_works():
    store.add_rule("invoice", "move", "Finance")
    newer = store.add_rule("INVOICE", "keep")

    assert [r["id"] for r in store.list_rules()] == [newer["id"]]

    store.delete_rule(newer["id"])
    assert store.list_rules() == []
    with pytest.raises(FileNotFoundError):
        store.delete_rule(newer["id"])


def test_most_specific_rule_wins():
    general = store.add_rule("MAT", "move", "Maths")
    specific = store.add_rule("21MAT", "move", "Documents/Study")

    rules = store.list_rules()
    assert store.matching_rule("21mat31 notes.pdf", rules)["id"] == specific["id"]
    assert store.matching_rule("matrix.pdf", rules)["id"] == general["id"]
    assert store.matching_rule("cv.pdf", rules) is None


def test_corrections_keep_newest_per_name_and_are_capped(monkeypatch):
    monkeypatch.setattr(store, "MAX_CORRECTIONS", 3)
    store.record_corrections([correction(os.path.join("Old", "a.pdf"), "Docs/A")])
    store.record_corrections([correction("A.PDF", "Docs/B")])
    store.record_corrections([correction(f"{n}.pdf", "Docs") for n in "xyz"])

    names = [c["name"] for c in store.list_corrections()]
    assert names == ["x.pdf", "y.pdf", "z.pdf"]

    store.record_corrections([correction("q.pdf", r"C:\Windows")])
    assert store.list_corrections()[-1]["chosen_destination"] is None

    store.clear_corrections()
    assert store.list_corrections() == []


# --- Rules engine -------------------------------------------------------------

def run_rules(root):
    scan = scan_folder(str(root))
    rules = store.list_rules()
    return {s["relative_path"]: s for s in apply_rules(root, scan, learned_rules=rules)}


def test_learned_rule_beats_built_in_rules_but_not_duplicates(tmp_path):
    write(tmp_path / "21MAT31 notes.pdf", b"notes")
    write(tmp_path / "setup_21MAT.exe", b"installer", age_days=90)
    write(tmp_path / "lecture.mp4", b"video")
    write(tmp_path / "21MAT copy.pdf", b"notes")  # Identical to the notes.
    rule = store.add_rule("21MAT", "move", "Documents/Study")
    store.add_rule("lecture", "keep")

    result = run_rules(tmp_path)

    notes = result["21MAT31 notes.pdf"]
    assert (notes["rule"], notes["action"], notes["destination"]) == ("learned", "move", "Documents/Study")
    assert notes["rule_id"] == rule["id"]
    # Beats "old installer" and "by file type".
    assert result["setup_21MAT.exe"]["rule"] == "learned"
    assert result["lecture.mp4"]["action"] == "keep"
    # An exact duplicate is still reported as one.
    duplicate = [s for s in result.values() if s["rule"] == "duplicate"]
    assert len(duplicate) == 1


def test_learned_rule_keeps_files_already_in_place(tmp_path):
    write(tmp_path / "Documents" / "Study" / "21MAT31.pdf")
    store.add_rule("21MAT", "move", "Documents/Study")

    [suggestion] = run_rules(tmp_path).values()

    assert suggestion["action"] == "keep"
    assert "Already in Documents/Study" in suggestion["reason"]


# --- Planner ------------------------------------------------------------------

class RecordingAnalyzer(AIAnalyzer):
    def __init__(self):
        self.files, self.examples = [], None

    def analyze(self, files):
        raise NotImplementedError

    def analyze_stream(self, files, examples=(), context=None):
        self.files, self.examples = files, examples
        for file in files:
            yield FileAnalysis(
                relative_path=file["relative_path"], category="documents",
                subcategory="other", action="keep", confidence=0.5, reason="ok",
            )


def test_planner_applies_rules_counts_hits_and_passes_corrections(tmp_path):
    write(tmp_path / "21MAT31.pdf", b"a")
    write(tmp_path / "invoice.pdf", b"b")
    store.add_rule("21MAT", "move", "Documents/Study")
    store.record_corrections([correction("tax 2024.pdf", "Documents/Taxes")])
    analyzer = RecordingAnalyzer()

    events = list(stream_plan(str(tmp_path), analyzer_factory=lambda: analyzer))

    rules_event = events[0]
    assert [s["rule"] for s in rules_event["suggestions"]] == ["learned"]
    assert "Documents/Taxes" in rules_event["destinations"]
    assert [f["name"] for f in analyzer.files] == ["invoice.pdf"]
    assert analyzer.examples[0]["chosen_destination"] == "Documents/Taxes"
    assert store.list_rules()[0]["hits"] == 1


# --- Prompts ------------------------------------------------------------------

def test_relevant_examples_share_words_with_the_batch():
    corrections = [
        stored("Electricity bill March.pdf", "Documents/Finance"),
        stored("DBMS notes unit 2.pdf", "Documents/Study"),
        stored("holiday.jpg", "Images/Photos", category="images"),
        stored("random.pdf", "Documents/Personal", action="keep"),
    ]
    folders = GROUPS["documents"]["folders"]
    batch = [doc("DBMS unit 5 notes.pdf"), doc("Electricity bill April.pdf")]

    examples = relevant_examples(batch, corrections, "documents", folders)

    # Sorted by shared words: "dbms", "notes", "unit" beat "electricity", "bill".
    assert examples == [
        ("DBMS notes unit 2.pdf", "study"),
        ("Electricity bill March.pdf", "finance"),
    ]


def test_custom_folders_become_labels_and_examples_lead_the_system_prompt():
    corrections = [stored("tax 2024 return.pdf", "Documents/Taxes")]
    folders = GROUPS["documents"]["folders"]

    learned = learned_folders(corrections, "documents", folders)
    assert learned == [("taxes", "Documents/Taxes", "a folder this user chose before")]

    system = build_system_prompt("documents", folders + learned, [("tax 2024 return.pdf", "taxes")])
    examples = system.split("Examples of good choices:\n")[1]
    assert examples.startswith("tax 2024 return.pdf -> taxes (this user's own choice")


def test_ai_can_answer_with_a_learned_folder():
    analyzer = ScriptedAnalyzer(["2|taxes|8|tax return like before"])
    corrections = [stored("tax 2024 return.pdf", "Documents/Taxes")]

    result = by_path(analyzer.analyze_stream([doc("tax 2025 return.pdf")], examples=corrections))

    assert result["tax 2025 return.pdf"].destination == "Documents/Taxes"
    system, user = analyzer.prompts[0]
    assert "taxes: a folder this user chose before" in system
    assert "tax 2024 return.pdf -> taxes (this user's own choice" in system
    assert user.startswith("Items:")


# --- API ----------------------------------------------------------------------

def test_rules_api_and_corrections_recorded_on_apply(tmp_path):
    client = TestClient(app)

    created = client.post("/api/rules", json={"contains": "21MAT", "action": "move", "destination": "Study"})
    assert created.status_code == 200
    assert client.post("/api/rules", json={"contains": "x", "action": "keep"}).status_code == 400

    write(tmp_path / "a.pdf")
    stats = (tmp_path / "a.pdf").stat()
    response = client.post("/api/execute", json={
        "path": str(tmp_path),
        "operations": [{
            "relative_path": "a.pdf", "action": "move", "destination": "Study",
            "size": stats.st_size, "modified": stats.st_mtime,
        }],
        "corrections": [correction("a.pdf", "Study")],
    })
    assert response.status_code == 200

    learned = client.get("/api/learned").json()
    assert learned["rules"][0]["contains"] == "21MAT"
    assert learned["corrections"] == 1
    assert learned["recent_corrections"][0]["name"] == "a.pdf"

    assert client.delete(f"/api/rules/{created.json()['id']}").status_code == 200
    assert client.delete("/api/rules/nope").status_code == 404
    assert client.delete("/api/corrections").json() == {"corrections": 0}


def test_build_plan_without_ai_still_applies_rules(tmp_path):
    write(tmp_path / "21MAT31.pdf")
    store.add_rule("21MAT", "move", "Documents/Study")

    result = build_plan(str(tmp_path), use_ai=False)

    assert result["suggestions"][0]["destination"] == "Documents/Study"
