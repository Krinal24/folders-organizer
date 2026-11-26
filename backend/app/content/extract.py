import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

from app.content import ocr


# Enough for the model to tell what a document is about; on a CPU-bound
# local model every extra character costs reading time.
DEFAULT_MAX_CHARS = 200

# Don't open huge files just to read their first lines.
MAX_FILE_SIZE = 50 * 1024 * 1024

PDF_PAGES = 2

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".rtf"}

# Office Open XML: (part to read, tag that holds text).
OOXML_PARTS = {
    ".docx": ("word/document.xml", "t"),
    ".pptx": ("ppt/slides/slide1.xml", "t"),
    ".xlsx": ("xl/sharedStrings.xml", "t"),
}

SUPPORTED_SUFFIXES = TEXT_SUFFIXES | set(OOXML_PARTS) | {".pdf"}

# Words that say nothing about what a document is.
GENERIC_WORDS = {
    "doc", "docs", "document", "documents", "file", "files", "scan", "scanned",
    "adobe", "camscanner", "untitled", "download", "downloads", "new", "copy",
    "final", "print", "output", "export", "image", "img", "pdf", "page",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec", "the", "and", "for",
}

# Footers that scanning apps stamp on every page; they say nothing.
SCANNER_WATERMARKS = re.compile(
    r"scanned (with|by) (camscanner|adobe scan)|camscanner|adobe scan",
    re.IGNORECASE,
)

# pypdf logs a warning for every malformed object; that's noise here.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def name_is_unclear(name: str) -> bool:
    """True when a file name doesn't say what the file is about.

    "83319332-4dc1-4775.pdf", "DOC-20221021-WA0004.pdf" and
    "Adobe Scan 10 Dec 2022.pdf" are unclear; "Answer Key.pdf" is not.
    """
    # "bescom1910payment" -> bescom, payment. Words need 4+ letters, so
    # code fragments like "ACK" in "ACK8131601" or "WA" in "WA0004" don't count.
    words = re.findall(r"[A-Za-z]+", Path(name).stem)
    meaningful = [
        word for word in words
        if len(word) >= 4 and word.lower() not in GENERIC_WORDS
    ]
    return not meaningful


def _clean(text: str, max_chars: int) -> str:
    # One line, no "|" (it separates fields in the AI reply format).
    text = re.sub(r"[\s|]+", " ", text).strip()
    text = "".join(char for char in text if char.isprintable())
    return text[:max_chars].rstrip()


def _pdf_text(path: Path, max_chars: int) -> str:
    reader = PdfReader(path)
    if reader.is_encrypted:
        return ""
    parts = []
    for page in reader.pages[:PDF_PAGES]:
        parts.append(page.extract_text() or "")
        if sum(len(part) for part in parts) >= max_chars * 2:
            break
    return " ".join(parts)


def looks_like_text(text: str) -> bool:
    """False for OCR gibberish, e.g. from handwriting: "xlu-+cLO cu.:a-l- boe"."""
    tokens = text.split()
    words = [
        token for token in tokens
        if re.fullmatch(r"[A-Za-z][a-z]{2,}|[A-Z]{3,}", token.strip(".,:;()[]'\"-"))
    ]
    # Measured on real scans: printed pages, forms and maths score 0.28+,
    # handwriting mostly below 0.3, so long texts get a little more slack.
    share = len(words) / max(len(tokens), 1)
    return len(words) >= 3 and (share >= 0.35 or (len(words) >= 20 and share >= 0.25))


def _scanned_pdf_text(path: Path) -> str:
    text = SCANNER_WATERMARKS.sub(" ", ocr.read_scanned_pdf(path))
    return text if looks_like_text(text) else ""


def _ooxml_text(path: Path, part: str, tag: str) -> str:
    with zipfile.ZipFile(path) as archive:
        if part not in archive.namelist():
            return ""
        root = ElementTree.fromstring(archive.read(part))
    # Match the tag in any namespace: {ns}t
    return " ".join(
        element.text or ""
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == tag
    )


def _plain_text(path: Path, max_chars: int) -> str:
    with open(path, "rb") as file:
        raw = file.read(max_chars * 4)
    return raw.decode("utf-8", errors="ignore")


def extract_snippet(
    path: Path, max_chars: int = DEFAULT_MAX_CHARS, read_scans: bool = True
) -> str:
    """The first few hundred characters of a document's text, or "".

    A PDF with no text layer (a scan) is read with OCR when `read_scans`
    is set and OCR is available. Never raises: unreadable, encrypted or
    unsupported files just give "".
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return ""

    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return ""
        if suffix == ".pdf":
            text = _pdf_text(path, max_chars)
        elif suffix in OOXML_PARTS:
            text = _ooxml_text(path, *OOXML_PARTS[suffix])
        else:
            text = _plain_text(path, max_chars)
    except Exception:
        # Corrupt PDFs and zips raise a zoo of exception types. A PDF
        # pypdf can't parse may still render, so it gets the OCR try.
        if suffix != ".pdf":
            return ""
        text = ""

    text = _clean(text, max_chars)
    if not text and suffix == ".pdf" and read_scans:
        text = _clean(_scanned_pdf_text(path), max_chars)
    return text
