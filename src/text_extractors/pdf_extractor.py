from typing import Optional
import fitz  # PyMuPDF
from src.text_extractors.ocr_extractor import extract_text_by_ocr

def extract_text_from_pdf(path: str) -> Optional[str]:
    # 1) מנסה קודם טקסט חיובית (לא סרוק)
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

    # אם חילוץ טקסט לא החזיר כמעט כלום — ננסה OCR
    if not text or len(text.replace("\n", " ").strip()) < 40:
        # העדפת שפות ל-OCR: אם התקנת "heb", שימי heb קודם; אחרת אפשר ["eng"]
        lang_order = ["heb", "eng"]
        text_ocr = extract_text_by_ocr(path, lang_order=lang_order)
        if text_ocr:
            return text_ocr

    return text or None
