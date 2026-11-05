"""OCR fallback for scanned pages. Requires the Tesseract binary (apt install tesseract-ocr)."""
import io

def ocr_page(page) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    pix = page.get_pixmap(dpi=200)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return pytesseract.image_to_string(img)
    except Exception:
        return ""
