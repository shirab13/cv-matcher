from pathlib import Path
from src.text_extractors.docx_extractor import extract_text_from_docx
from src.text_extractors.pdf_extractor import extract_text_from_pdf

def extract_text_any(path: str) -> str:
    """
    Extract text from TXT/DOCX/PDF.
    For PDFs, OCR fallback is handled inside pdf_extractor.
    Returns '' if nothing extracted.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""

    suf = p.suffix.lower()
    try:
        if suf == ".txt":
            return p.read_text(encoding="utf-8", errors="ignore")
        if suf == ".docx":
            return extract_text_from_docx(str(p)) or ""
        if suf == ".pdf":
            return extract_text_from_pdf(str(p)) or ""
        return ""
    except Exception:
        return ""
