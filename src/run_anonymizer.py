from anonymizer import anonymize_docx_file, anonymize_pdf_file
from pathlib import Path
import pytesseract
import os

# הגדרה ל-Tesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# קלט/פלט - תעדכני את הנתיבים שלך כאן:
INPUT_DIR  = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\input"
OUTPUT_DIR = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\output"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# חיפוש כל הקבצים
all_files = [str(p) for p in Path(INPUT_DIR).rglob('*') if p.is_file()]

for path in all_files:
    ext = Path(path).suffix.lower()
    out_path = str(Path(OUTPUT_DIR) / Path(path).name)
    try:
        if ext == ".docx":
            anonymize_docx_file(path, out_path)
        elif ext == ".pdf":
            anonymize_pdf_file(path, out_path)
        else:
            continue
        print(f"✅ סודר: {path}")
    except Exception as e:
        print(f"❌ נכשל ({path}): {e}")

print("\n===== סיום עיבוד =====")
