from typing import Optional
import fitz  # PyMuPDF
from src.text_extractors.ocr_extractor import extract_text_by_ocr

def extract_text_from_pdf(path: str) -> Optional[str]:
    """Extract text from PDF; if weak/empty -> try OCR fallback."""
    try:
        doc = fitz.open(path)
    except Exception:
        doc = None

    text = ""
    if doc is not None:
        parts = []
        for page in doc:
            try:
                t = page.get_text()
            except Exception:
                t = ""
            if t:
                parts.append(t)
        doc.close()
        text = "\n".join(parts).strip()

    # OCR fallback אם הטקסט דל
    if not text or len(text.replace("\n", " ").strip()) < 40:
        text_ocr = extract_text_by_ocr(path, lang_order=["heb","eng"])
        if text_ocr:
            return text_ocr

    return text or None