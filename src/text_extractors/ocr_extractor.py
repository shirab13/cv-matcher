import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # <-- את זה להחליף לנתיב שמצאת
# src/text_extractors/ocr_extractor.py
from typing import Optional, List
from pathlib import Path
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
POPPLER_PATH = r"C:\Users\shira\Downloads\Release-25.07.0-0\poppler-25.07.0\Library\bin"

# אם נתיב ברירת מחדל לא עובד אצלך – בטלי הערה בשורה הבאה ועדכני את הנתיב:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def _page_to_image(page: "fitz.Page", dpi: int = 200) -> Image.Image:
    # רסטריזציה של עמוד PDF לתמונה
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return img

def _ocr_images(images: List[Image.Image], lang: str = "eng") -> str:
    texts = []
    for img in images:
        try:
            txt = pytesseract.image_to_string(img, lang=lang)
        except Exception:
            txt = ""
        if txt:
            texts.append(txt)
    return "\n".join(texts).strip()

def extract_text_by_ocr(pdf_path: str, lang_order: List[str]) -> Optional[str]:
    """מנסה OCR לפי סדר שפות נתון (למשל ["heb","eng"]). מחזיר טקסט או None."""
    p = Path(pdf_path)
    if not p.exists():
        return None
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None

    # רסטריזציה של כל העמודים לתמונות
    images = []
    for page in doc:
        try:
            images.append(_page_to_image(page, dpi=230))  # DPI מעט גבוה לשיפור OCR
        except Exception:
            continue
    doc.close()

    if not images:
        return None

    # ננסה לפי סדר שפות עד שנקבל טקסט "מספיק"
    for lang in lang_order:
        text = _ocr_images(images, lang=lang)
        # סף פשוט: אם יש יותר מ-40 תווים ולא רובם ריקים—נקבל
        if text and len(text.replace("\n", " ").strip()) > 40:
            return text
    # אם אף שפה לא החזירה תוכן משמעותי:
    return None
