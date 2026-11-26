"""Read text from scanned PDFs, whose pages are pictures.

The first page is rendered to an image (pypdfium2) and read with the OCR
engine built into Windows 10/11, so nothing is installed or downloaded and
nothing leaves the machine. Elsewhere OCR is unavailable and scanned PDFs
are treated as unreadable, as before.
"""
import asyncio
import logging
import sys
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Long side of the rendered page. Big enough for body text, small enough
# to stay well under a second per page.
RENDER_PIXELS = 2000


def _engine():
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.media.ocr import OcrEngine
    except ImportError:
        return None
    # The languages the user has installed in Windows settings.
    return OcrEngine.try_create_from_user_profile_languages()


_ENGINE = None
_CHECKED = False


def engine():
    global _ENGINE, _CHECKED
    if not _CHECKED:
        try:
            _ENGINE = _engine()
        except Exception as error:  # Broken WinRT install, no language pack.
            log.warning("Windows OCR unavailable: %s", error)
        _CHECKED = True
    return _ENGINE


def available() -> bool:
    return engine() is not None


def _bitmap(image: Image.Image):
    from winrt.windows.graphics.imaging import (
        BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap,
    )
    from winrt.windows.storage.streams import DataWriter

    rgba = image.convert("RGBA")
    writer = DataWriter()
    writer.write_bytes(rgba.tobytes("raw", "BGRA"))
    return SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(),
        BitmapPixelFormat.BGRA8,
        rgba.width,
        rgba.height,
        BitmapAlphaMode.PREMULTIPLIED,
    )


def read_image(image: Image.Image) -> str:
    """The text in an image, or "" if OCR is unavailable or finds none."""
    ocr = engine()
    if ocr is None:
        return ""
    limit = type(ocr).max_image_dimension  # A static property.
    if max(image.size) > limit:
        image = image.copy()
        image.thumbnail((limit, limit))

    async def recognize():
        return await ocr.recognize_async(_bitmap(image))

    # Runs in a worker thread with no event loop of its own.
    return asyncio.run(recognize()).text or ""


def render_first_page(path: Path) -> Image.Image | None:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    try:
        if len(pdf) == 0:
            return None
        page = pdf[0]
        width, height = page.get_size()  # In points, 1/72 inch.
        scale = RENDER_PIXELS / max(width, height, 1)
        return page.render(scale=scale, grayscale=True).to_pil()
    finally:
        pdf.close()


def read_scanned_pdf(path: Path) -> str:
    """OCR the first page of a PDF. Never raises; "" when it can't."""
    if not available():
        return ""
    try:
        image = render_first_page(path)
        return read_image(image) if image is not None else ""
    except Exception as error:
        log.info("OCR failed for %s: %s", path.name, error)
        return ""
