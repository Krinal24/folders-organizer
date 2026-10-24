import os
import zipfile

import pytest

from app.ai.analyzer import AIAnalyzer
from app.content.extract import extract_snippet, name_is_unclear
from app.models.ai_schemas import CleanupPlan, FileAnalysis
from app.planner import build_plan


@pytest.mark.parametrize("name, unclear", [
    ("83319332-4dc1-4775-8054-36be5bdf81e1.pdf", True),
    ("DOC-20221021-WA0004.pdf", True),
    ("Adobe Scan 10 Dec 2022.pdf", True),
    ("ACK813160110300726.pdf", True),
    ("CamScanner 09-16-2022 10.47.53.pdf", True),
    ("Answer Key.pdf", False),
    ("bescom1910payment.pdf", False),
    ("Krinal_Resume_2026.pdf", False),
    ("21MAT21 - revised.docx", False),
])
def test_name_is_unclear(name, unclear):
    assert name_is_unclear(name) is unclear


def make_pdf(path, text):
    content = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 100]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)
    path.write_bytes(body)


def make_ooxml(path, part, xml):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(part, xml)


def test_extracts_pdf_text(tmp_path):
    make_pdf(tmp_path / "a.pdf", "Electricity bill payment receipt")

    assert extract_snippet(tmp_path / "a.pdf") == "Electricity bill payment receipt"


def test_extracts_docx_pptx_xlsx(tmp_path):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    make_ooxml(tmp_path / "a.docx", "word/document.xml",
               f"<w:document {w}><w:body><w:p><w:r><w:t>Semester</w:t></w:r>"
               f"<w:r><w:t>exam timetable</w:t></w:r></w:p></w:body></w:document>")
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    make_ooxml(tmp_path / "b.pptx", "ppt/slides/slide1.xml",
               f"<p:sld xmlns:p='p' {a}><a:t>Quarterly review</a:t></p:sld>")
    make_ooxml(tmp_path / "c.xlsx", "xl/sharedStrings.xml",
               "<sst xmlns='s'><si><t>Name</t></si><si><t>Marks</t></si></sst>")

    assert extract_snippet(tmp_path / "a.docx") == "Semester exam timetable"
    assert extract_snippet(tmp_path / "b.pptx") == "Quarterly review"
    assert extract_snippet(tmp_path / "c.xlsx") == "Name Marks"


def test_text_is_one_line_without_pipes_and_truncated(tmp_path):
    (tmp_path / "a.txt").write_text("Line one | two\n\n  three " + "x" * 500, encoding="utf-8")

    snippet = extract_snippet(tmp_path / "a.txt", max_chars=30)

    assert snippet.startswith("Line one two three")
    assert "|" not in snippet and "\n" not in snippet
    assert len(snippet) <= 30


def test_unreadable_files_give_empty_text(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 garbage")
    (tmp_path / "broken.docx").write_bytes(b"not a zip")
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8")

    assert extract_snippet(tmp_path / "broken.pdf") == ""
    assert extract_snippet(tmp_path / "broken.docx") == ""
    assert extract_snippet(tmp_path / "photo.jpg") == ""


class RecordingAnalyzer(AIAnalyzer):
    def __init__(self):
        self.files = []

    def analyze(self, files):
        self.files = files
        return CleanupPlan(analyses=[
            FileAnalysis(
                relative_path=file["relative_path"],
                category="documents",
                subcategory="finance",
                action="move",
                destination="Documents/Finance",
                confidence=0.8,
                reason="Suggested by the AI.",
            )
            for file in files
        ])


def test_planner_reads_unclear_documents_only(tmp_path):
    make_pdf(tmp_path / "83319332.pdf", "Income Tax Return acknowledgement")
    make_pdf(tmp_path / "Answer Key.pdf", "Question 1 answer")
    analyzer = RecordingAnalyzer()

    result = build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    sent = {f["name"]: f.get("snippet") for f in analyzer.files}
    assert sent == {
        "83319332.pdf": "Income Tax Return acknowledgement",
        "Answer Key.pdf": None,
    }
    by_path = {s["relative_path"]: s for s in result["suggestions"]}
    assert by_path["83319332.pdf"]["used_content"] is True
    assert "Income Tax Return" in by_path["83319332.pdf"]["reason"]
    assert by_path["Answer Key.pdf"]["used_content"] is False


def test_unclear_documents_without_text_skip_the_ai(tmp_path):
    (tmp_path / "CamScanner 09-16-2022.pdf").write_bytes(b"%PDF-1.4 scanned image only")
    (tmp_path / "Mine").mkdir()
    (tmp_path / "Mine" / "DOC-2022-WA0004.pdf").write_bytes(b"%PDF-1.4 scan")
    analyzer = RecordingAnalyzer()

    result = build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    assert analyzer.files == []
    by_path = {s["relative_path"]: s for s in result["suggestions"]}
    top = by_path["CamScanner 09-16-2022.pdf"]
    assert (top["action"], top["destination"], top["rule"]) == ("move", "Documents/Other", "unclear_document")
    assert by_path[os.path.join("Mine", "DOC-2022-WA0004.pdf")]["action"] == "keep"


def test_reading_contents_can_be_turned_off(tmp_path, monkeypatch):
    make_pdf(tmp_path / "83319332.pdf", "Income Tax Return")
    analyzer = RecordingAnalyzer()

    build_plan(str(tmp_path), analyzer_factory=lambda: analyzer, read_contents=False)
    assert analyzer.files[0].get("snippet") is None

    monkeypatch.setenv("AI_READ_CONTENTS", "off")
    build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)
    assert analyzer.files[0].get("snippet") is None


def test_all_mode_reads_clear_names_too(tmp_path, monkeypatch):
    make_pdf(tmp_path / "Answer Key.pdf", "Question 1 answer")
    monkeypatch.setenv("AI_READ_CONTENTS", "all")
    analyzer = RecordingAnalyzer()

    build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    assert analyzer.files[0]["snippet"] == "Question 1 answer"
