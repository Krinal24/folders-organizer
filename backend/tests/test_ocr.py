import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ai.analyzer import AIAnalyzer
from app.content import ocr
from app.content.extract import extract_snippet, looks_like_text
from app.models.ai_schemas import FileAnalysis
from app.planner import build_plan
from tests.test_content import make_pdf

REAL_READ = ocr.read_scanned_pdf  # Saved before conftest turns OCR off.


def scanned_pdf(path):
    """A PDF whose only page is an image: no text layer, like a scan."""
    Image.new("L", (200, 100), 255).save(path, "PDF")
    return path


@pytest.mark.parametrize("text, readable", [
    ("Electricity bill payment receipt for October", True),
    ("NITTE MEENAKSHI INSTITUTE OF TECHNOLOGY Mid semester exam", True),
    ("(iii) Taking the limit we get f(x) = 2x + 3 which is equal", True),
    ("09 Q xlu-+cLO cu.:a-l- 9 Co.-so be (7) P, d. QC-mu-e.-A- boe kct", False),
    ("o o C) o o o 2021", False),
    ("", False),
])
def test_looks_like_text(text, readable):
    assert looks_like_text(text) is readable


def test_scanned_pdf_is_read_with_ocr(tmp_path, monkeypatch):
    calls = []

    def fake_ocr(path):
        calls.append(path.name)
        return "Electricity bill for October 2022 Scanned with CamScanner"

    monkeypatch.setattr(ocr, "read_scanned_pdf", fake_ocr)

    assert extract_snippet(scanned_pdf(tmp_path / "scan.pdf")) == "Electricity bill for October 2022"
    assert extract_snippet(tmp_path / "scan.pdf", read_scans=False) == ""
    assert calls == ["scan.pdf"]


def test_pdfs_with_text_are_not_ocrd(tmp_path, monkeypatch):
    make_pdf(tmp_path / "a.pdf", "Answer key")
    monkeypatch.setattr(ocr, "read_scanned_pdf", lambda path: pytest.fail("OCR called"))

    assert extract_snippet(tmp_path / "a.pdf") == "Answer key"


def test_ocr_gibberish_counts_as_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "read_scanned_pdf", lambda path: "xlu-+cLO cu.:a-l- boe kct (7) P,")

    assert extract_snippet(scanned_pdf(tmp_path / "notes.pdf")) == ""


@pytest.mark.skipif(not ocr.available(), reason="Windows OCR not available here")
def test_real_ocr_reads_a_rendered_page(tmp_path):
    image = Image.new("L", (1200, 300), 255)
    ImageDraw.Draw(image).text(
        (40, 100), "Electricity bill payment", fill=0, font=ImageFont.load_default(size=72)
    )
    image.save(tmp_path / "scan.pdf", "PDF")

    text = REAL_READ(tmp_path / "scan.pdf")

    assert "Electricity" in text and "payment" in text


# --- Second look: unsure answers are asked again with the file's text --------

class TwoPassAnalyzer(AIAnalyzer):
    """Unsure from names alone; sure once it sees text."""

    def __init__(self, fail_second=False):
        self.calls = []
        self.fail_second = fail_second

    def analyze(self, files):
        raise NotImplementedError

    def analyze_stream(self, files, examples=(), context=None):
        self.calls.append({f["name"]: f.get("snippet") for f in files})
        if len(self.calls) > 1 and self.fail_second:
            raise RuntimeError("model went away")
        for file in files:
            sure = file.get("snippet") or file["name"] == "Resume Krinal.pdf"
            yield FileAnalysis(
                relative_path=file["relative_path"],
                category="documents",
                subcategory="finance" if sure else "other",
                action="move",
                destination="Documents/Finance" if sure else "Documents/Other",
                confidence=0.9 if sure else 0.5,
                reason="Suggested by the AI.",
            )


def test_unsure_answers_get_a_second_look_with_text(tmp_path):
    make_pdf(tmp_path / "Statement March.pdf", "HDFC Bank account statement")
    make_pdf(tmp_path / "Resume Krinal.pdf", "Krinal resume")
    (tmp_path / "Notes March.pdf").write_bytes(b"%PDF-1.4 nothing readable")
    analyzer = TwoPassAnalyzer()

    result = build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    first, second = analyzer.calls
    assert set(first) == {"Statement March.pdf", "Resume Krinal.pdf", "Notes March.pdf"}
    assert second == {"Statement March.pdf": "HDFC Bank account statement"}

    by_path = {s["relative_path"]: s for s in result["suggestions"]}
    assert len(result["suggestions"]) == 3  # One answer per file.
    statement = by_path["Statement March.pdf"]
    assert (statement["destination"], statement["used_content"]) == ("Documents/Finance", True)
    assert "HDFC Bank" in statement["reason"]
    # Nothing to read: the first answer stands.
    assert by_path["Notes March.pdf"]["destination"] == "Documents/Other"
    assert by_path["Resume Krinal.pdf"]["used_content"] is False


def test_failed_second_look_keeps_the_first_answers(tmp_path):
    make_pdf(tmp_path / "Statement March.pdf", "HDFC Bank account statement")
    analyzer = TwoPassAnalyzer(fail_second=True)

    result = build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    [only] = result["suggestions"]
    assert only["destination"] == "Documents/Other" and not result.get("error")


def test_no_second_look_when_reading_is_off(tmp_path, monkeypatch):
    make_pdf(tmp_path / "Statement March.pdf", "HDFC Bank account statement")
    monkeypatch.setenv("AI_READ_CONTENTS", "off")
    analyzer = TwoPassAnalyzer()

    build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    assert len(analyzer.calls) == 1


def test_scanned_unclear_pdf_goes_to_the_ai_with_its_ocr_text(tmp_path, monkeypatch):
    scanned_pdf(tmp_path / "CamScanner 09-16-2022.pdf")
    monkeypatch.setattr(ocr, "read_scanned_pdf", lambda path: "Income Tax Return acknowledgement")
    analyzer = TwoPassAnalyzer()

    result = build_plan(str(tmp_path), analyzer_factory=lambda: analyzer)

    assert analyzer.calls == [{"CamScanner 09-16-2022.pdf": "Income Tax Return acknowledgement"}]
    assert result["suggestions"][0]["destination"] == "Documents/Finance"
