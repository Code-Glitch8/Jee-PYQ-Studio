"""OCR helpers. The positioned OCR used by the pipeline lives in extraction.layout.ocr_lines (needs the Tesseract binary:
apt install tesseract-ocr). This module keeps the original text-only helper and a cheap availability check."""
import io, shutil


def available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def ocr_page(page) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    pix = page.get_pixmap(dpi=300)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return pytesseract.image_to_string(img, lang="eng", config="--psm 6")
    except Exception:
        return ""
