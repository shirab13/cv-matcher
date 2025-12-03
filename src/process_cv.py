from pathlib import Path
import os

from src.anonymizer import anonymize_docx_file, anonymize_pdf_file
from src.utils import db as cv_db

# לעדכן אם צריך – אותם נתיבים כמו ב-run_anonymizer
INPUT_DIR  = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\input"
OUTPUT_DIR = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\output"
CV_DB_PATH = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\data\client.sqlite3"  # תעדכני לשם ה-DB שלך

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def process_uploaded_cv(temp_path: str, original_filename: str, job_id: int) -> int:
    """
    מקבלת קובץ שהועלה זמנית (temp_path),
    שומרת אותו לתיקיית input,
    מריצה אנונימיזציה ל-output,
    רושמת ב-DB ומקשרת למשרה.
    
    מחזירה: cv_id (המספר הרץ בטבלת candidates).
    """

    # 1. יעד בקלט ויעד בפלט
    ext = Path(original_filename).suffix.lower()
    safe_name = Path(original_filename).name
    input_path = str(Path(INPUT_DIR) / safe_name)
    output_path = str(Path(OUTPUT_DIR) / safe_name)

    # 2. מעתיקה את הקובץ הזמני ל-input
    Path(temp_path).replace(input_path)

    # 3. מריצה אנונימיזציה לפי סוג קובץ
    if ext == ".docx":
        anonymize_docx_file(input_path, output_path)
    elif ext == ".pdf":
        anonymize_pdf_file(input_path, output_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # 4. רושמת ב-DB של הלקוח
    con = cv_db.connect(CV_DB_PATH)
    try:
        # מוסיפה/מעדכנת רשומה בטבלת candidates על בסיס הנתיב של הקובץ האנונימי
        cv_id = cv_db.upsert_candidate(con, output_path)

        # קישור ל-job_id מה-DB של auth_server
        cv_db.link_cv_to_job(con, cv_id, job_id)

    finally:
        con.close()

    return cv_id
