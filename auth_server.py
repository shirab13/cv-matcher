# auth_server.py
import os
import json
import sqlite3
import re
import threading
from functools import wraps
from flask import abort
import traceback
from uuid import uuid4
from pathlib import Path
from werkzeug.utils import secure_filename
from functools import wraps
from flask import abort
# אנונימיזר + upsert לקנדידייט
from src.anonymizer import anonymize_docx_file, anonymize_pdf_file
from src.utils.db import upsert_candidate
from src.utils import db as dbutil
from src.text_extractors.universal import extract_text_any
from src.run_scoring import infer_birth_year_simple, age_from_birth_year, apply_age_penalty
from src.scoring.experience_score import extract_estimated_experience_years
from src.text_extractors.universal import extract_text_any
from src.scoring.experience_score import (
    extract_required_years_from_job_text,
    extract_relevant_experience_years,
    calculate_years_experience_score,
)
from src.scoring.distance_score import (
    extract_candidate_city,
    calculate_distance_km,
    calculate_distance_score,
)
from flask import (
    Flask,
    request,
    jsonify,
    session,
    redirect,
    render_template,
    send_file,
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
from uuid import uuid4
from werkzeug.utils import secure_filename

# חיבור ל־DB של המועמדים + ציון גיל
from src.utils.db import connect as cv_connect, upsert_candidate

# פונקציות האנונימיזציה + נתיבי input/output
from src.anonymizer import (
    anonymize_docx_file,
    anonymize_pdf_file,
    INPUT_DIR,
    OUTPUT_DIR,
)

DB_PATH = "cv_matcher.db"
print("DB ABS PATH =", os.path.abspath(DB_PATH))

# איפה נשמור את הקו"ח הגולמי ואת הקובץ האנונימי
_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR  = os.path.join(_BASE_DIR, "src", "input")
OUTPUT_DIR = os.path.join(_BASE_DIR, "src", "output")
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
app = Flask(__name__)
app.secret_key = "dev-secret-change-me"   # להחליף בסוד אמיתי בפרודקשן
CORS(app)
def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS

def _normalize_text(text: str) -> str:
    """
    מנרמל טקסט:
    - לאותיות קטנות
    - מסיר סימני פיסוק, משאיר אותיות/מספרים
    - מרווחים בודדים
    """
    if not text:
        return ""
    text = text.lower()
    # משאירים אותיות (עברית/אנגלית) ומספרים, שאר התווים -> רווח
    text = re.sub(r"[^a-zA-Zא-ת0-9+/#]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

HE_PREFIXES = ("ו", "ה", "ב", "ל", "כ", "מ", "ש")

ALIASES = {
    # English
    "english": "אנגלית",
    "eng": "אנגלית",
    "en": "אנגלית",
    "האנגלית": "אנגלית",
    "אנגלית": "אנגלית",

    # Hebrew
    "hebrew": "עברית",
    "ivrit": "עברית",
    "he": "עברית",
    "העברית": "עברית",
    "עברית": "עברית",
    
    # Python
    "python": "פייתון",
    "py": "פייתון",
    "פייתון": "פייתון",

    # JavaScript / TypeScript
    "javascript": "גאווהסקריפט",
    "js": "גאווהסקריפט",
    "typescript": "טייפסקריפט",
    "ts": "טייפסקריפט",

    # React / Node
    "react": "react",
    "reactjs": "react",
    "node": "node",
    "nodejs": "node",
    "node.js": "node",
    "express": "express",
}

def _normalize_token(token: str) -> str:
    token = token.strip().lower()

    # מסירים סימנים כמו נקודות/פסיקים מסביב (למשל node.js, python,)
    token = token.strip(".,:;()[]{}<>\"'")

    # normalize some known punctuation cases
    token = token.replace("nodejs", "node")
    token = token.replace("node.js", "node")
    token = token.replace("reactjs", "react")

    # הסרת תחיליות בעברית: "באנגלית" -> "אנגלית", "בפייתון" -> "פייתון"
    changed = True
    while changed and len(token) >= 3:
        changed = False
        for p in HE_PREFIXES:
            if token.startswith(p) and len(token) >= 4:
                token = token[1:]
                changed = True
                break

    # מפעילים aliases
    return ALIASES.get(token, token)




def _extract_keywords(text: str) -> set[str]:
    """
    מוציא "מילים משמעותיות" מטקסט:
    - מוריד לרשום אותיות קטנות
    - מפצל למילים
    - מסנן מילים קצרות ומילות עצירה בסיסיות
    """
    if not text:
        return set()

    text = text.lower()

    # מילות עצירה בסיסיות (גם קצת עברית וגם אנגלית)
    stopwords = {
        "של", "עם", "על", "או", "אם", "לא", "כן", "וכן", "ו", "the", "and", "for",
        "to", "in", "on", "a", "an", "is", "are", "of"
    }

    # \w תופס גם אותיות בעברית בפייתון (יוניקוד)
    words = re.findall(r"\w+", text)

    keywords = set()
    for w in words:
        w = _normalize_token(w)
        if len(w) >= 3 and w not in stopwords:
            keywords.add(w)

    return keywords




#פונקציה שמחזירה Coverage (K,N) במקום 0–10
def requirements_coverage(cv_text: str, requirements_text: str) -> tuple[int, int]:
    """
    מחזירה (covered, total)
    כל שורה/בולט בדרישות = דרישה אחת.
    דרישה נחשבת מכוסה אם לפחות חצי מהמילים המשמעותיות שלה מופיעות בקו"ח.
    """
    if not requirements_text:
        return (0, 0)

    raw_reqs = re.split(r"[\n;\u2022\-•]+", requirements_text)
    req_lines = [r.strip() for r in raw_reqs if r.strip()]
    if not req_lines:
        return (0, 0)

    cv_keywords = _extract_keywords(cv_text)
    if not cv_keywords:
        return (0, len(req_lines))

    covered = 0
    for line in req_lines:
        req_keywords = _extract_keywords(line)
        if not req_keywords:
            continue
        matched = sum(1 for w in req_keywords if w in cv_keywords)
        ratio = matched / len(req_keywords)
        if ratio >= 0.5:
            covered += 1

    return (covered, len(req_lines))


#פונקציה שמתרגמת Coverage לנקודות (40/10)
def requirements_points(cv_text: str, must_text: str, nice_text: str | None) -> dict:
    MUST_WEIGHT = 40.0
    NICE_WEIGHT = 10.0

    must_covered, must_total = requirements_coverage(cv_text, must_text)
    must_points = 0.0 if must_total == 0 else MUST_WEIGHT * (must_covered / must_total)

    # NICE: אם אין בכלל nice-to-have במשרה → נותנים את כל הנקודות
    if not nice_text or not nice_text.strip():
        nice_points = NICE_WEIGHT        # 10.0
        nice_covered = 0
        nice_total = 0
    else:
        nice_covered, nice_total = requirements_coverage(cv_text, nice_text)
        nice_points = 0.0 if nice_total == 0 else NICE_WEIGHT * (nice_covered / nice_total)

    return {
        "must": {"covered": must_covered, "total": must_total, "points": round(must_points, 2)},
        "nice": {"covered": nice_covered, "total": nice_total, "points": round(nice_points, 2)},
        "requirements_points": round(must_points + nice_points, 2)
    }


def score_requirements_from_text(cv_text: str, requirements_text: str) -> float:
    """
    מקבלת טקסט קו\"ח (cv_text) וטקסט דרישות משרה (requirements_text – משפטים/בולטים)
    ומחזירה ציון 0–10 לפי כמה דרישות כוסו ע\"י הקו\"ח.

    כל שורה/בולט בדרישות נחשבת "דרישה".
    דרישה נחשבת מכוסה אם לפחות חצי מהמילים המשמעותיות שלה מופיעות בקו\"ח.
    """
    if not requirements_text:
        # אם לא הוגדרו דרישות – אין מה לבדוק, נחזיר ציון מלא
        return 10.0

    # מפרקים לדרישות – לפי שורות / נקודות / נקודות־פסיק
    raw_reqs = re.split(r"[\n;\u2022\-•]+", requirements_text)
    req_lines = [r.strip() for r in raw_reqs if r.strip()]

    if not req_lines:
        return 10.0

    cv_keywords = _extract_keywords(cv_text)
    if not cv_keywords:
        # אין מילים משמעותיות בקו\"ח → לא כיסינו כלום
        return 0.0

    covered_reqs = 0

    for line in req_lines:
        req_keywords = _extract_keywords(line)
        if not req_keywords:
            # דרישה ללא מילים משמעותיות – נתייחס כאילו אין מה לבדוק
            continue

        # כמה מילים מהדרישה מופיעות בקו\"ח
        matched = sum(1 for w in req_keywords if w in cv_keywords)
        ratio = matched / len(req_keywords)

        # אם חצי ומעלה מהמילים הופיעו בקו\"ח – נספור אותה כ"מכוסה"
        if ratio >= 0.5:
            covered_reqs += 1

    if covered_reqs == 0:
        return 0.0

    score = (covered_reqs / len(req_lines)) * 10.0
    return round(score, 2)
# ----------------- ROUTES בסיס -----------------

@app.route("/")
def index():
    # דף ההתחברות – templates/login.html
    return render_template("login.html")
# ----------------- דף הרשמה -----------------


@app.route("/register", methods=["GET"])
def register_get():
    """
    דף הרשמה למנהלי HR – מציג את הטופס.
    """
    return render_template("register.html")

@app.route("/api/register", methods=["POST"])
def api_register():
    """
    API להרשמת מנהל/ת HR חדש/ה.
    יוצר רשומה בטבלת users עם is_approved=0.
    """
    data = request.get_json() or {}

    email = (data.get("email") or "").strip().lower()
    company_name = (data.get("company_name") or "").strip()
    password = (data.get("password") or "").strip()

    # ולידציה בסיסית
    if not email or not company_name or not password:
        return jsonify({
            "success": False,
            "message": "חובה למלא אימייל, שם חברה וסיסמה"
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "הסיסמה חייבת להיות באורך 6 תווים לפחות"
        }), 400

    conn = get_db()
    cur = conn.cursor()

    # בדיקה אם האימייל כבר קיים
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cur.fetchone() is not None:
        conn.close()
        return jsonify({
            "success": False,
            "message": "אימייל זה כבר רשום במערכת"
        }), 400

    # יצירת משתמש חדש ברירת מחדל: HR_MANAGER, is_approved=0
    password_hash = generate_password_hash(password)

    try:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, role, company_name, is_approved, manager_id)
            VALUES (?, ?, ?, ?, 0, NULL)
            """,
            (email, password_hash, "HR_LEAD", company_name),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "ההרשמה נקלטה בהצלחה. החשבון יופיע למנהל המערכת לאישור."
    }), 201


# -----------------helper להרשאות hr_LEAD בלבד -----------------
def hr_manager_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "message": "לא מחובר/ת"}), 401

        # היה: HR_MANAGER
        if session.get("role") != "HR_LEAD":
            return jsonify({"success": False, "message": "אין לך הרשאה לפעולה הזו"}), 403

        return f(*args, **kwargs)
    return wrapper
# -----------------קליטת משרה חדשה-----------------
@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = request.get_json() or {}

    title = (data.get("title") or "").strip()
    required_years_experience = data.get("required_years_experience")
    description = (data.get("description") or "").strip()
    must_req = (data.get("must_requirements") or "").strip()
    nice_req = (data.get("nice_to_have_requirements") or "").strip() or None
    location = (data.get("location") or "").strip() or None
    employment_type = (data.get("employment_type") or "").strip() or None
    work_mode = (data.get("work_mode") or "").strip() or None
    if required_years_experience in ("", None):
        required_years_experience = None
    else:
        try:
            required_years_experience = float(required_years_experience)
        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "message": "שנות ניסיון נדרשות חייב להיות מספר תקין"
            }), 400
    # ולידציה בסיסית
    if not title or not description or not must_req:
        return jsonify({
            "success": False,
            "message": "חובה למלא שם משרה, תיאור ודרישות חובה"
        }), 400

    # 🟣 ה־user שמחובר עכשיו
    current_user_id = session["user_id"]

    conn = get_db()
    cur = conn.cursor()

    # 🟣 מביאים את ה-manager_id של המשתמש המחובר
    cur.execute("SELECT manager_id FROM users WHERE id = ?", (current_user_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({
            "success": False,
            "message": "לא נמצא משתמש מחובר במערכת"
        }), 500

    manager_id = row["manager_id"]   # ⬅️ זה המספר 5 שאת רוצה

    # (אופציונלי) אם יכול להיות שאין manager_id בכלל:
    if manager_id is None:
        conn.close()
        return jsonify({
            "success": False,
            "message": "לא מוגדר מנהל עבור המשתמש, לא ניתן ליצור משרה"
        }), 400

    # יצירת המשרה עם ה-manager_id מהעמודה של המשתמש
    cur.execute(
        """
        INSERT INTO jobs (
            title, description, must_requirements,
            nice_to_have_requirements, location, employment_type,
            work_mode, required_years_experience, manager_id
        )
        VALUES (?,?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            description,
            must_req,
            nice_req,
            location,
            employment_type,
            work_mode,
            required_years_experience,
            manager_id,
        )    )

    job_id = cur.lastrowid
    conn.commit()
    conn.close()

    log_event(f"Job created: {title}", "info", current_user_id)

    return jsonify({
        "success": True,
        "message": "המשרה נוצרה בהצלחה",
        "job_id": job_id
    }), 201

@app.route("/api/recruiter/review", methods=["POST"])
def recruiter_review():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    if session.get("role") != "RECRUITER":
        return jsonify({"success": False, "message": "אין הרשאה"}), 403

    data = request.get_json() or {}

    job_id = data.get("job_id")
    cv_id = data.get("cv_id")
    status = data.get("status")
    feedback = data.get("feedback")
    human_score = data.get("human_score")

    if not job_id or not cv_id or not status:
        return jsonify({"success": False, "message": "חסרים נתונים"}), 400

    conn = sqlite3.connect("cv_matcher.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        UPDATE job_candidates
        SET recruiter_status = ?,
            recruiter_feedback = ?,
            reviewed_by_user_id = ?,
            reviewed_at = CURRENT_TIMESTAMP,
            human_score = COALESCE(?, human_score)
        WHERE job_id = ? AND cv_id = ?
    """, (status, feedback, session["user_id"], human_score, job_id, cv_id))

    conn.commit()
    conn.close()

    log_event(
        f"Recruiter feedback submitted for candidate {cv_id}",
        "info",
        session["user_id"],
    )
    return jsonify({"success": True, "message": "הסקירה נשמרה בהצלחה"})
# -----------------רשימת משרות קיימות-----------------
@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    """
    מחזיר רשימת משרות מסוננות לפי מנהל ה-HR של המשתמש.
    HR_LEAD → רואה את המשרות של עצמו (jobs.manager_id = user_id)
    HR_MANAGER / RECRUITER → רואים משרות של המנהל שלהם (jobs.manager_id = users.manager_id)
    DEVOPS → רואה הכל.
    """

    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    user_id = session["user_id"]
    role = session.get("role")

    conn = get_db()
    cur = conn.cursor()

    manager_key = None  # זה הערך שנשתמש בו ב-WHERE manager_id = ?

    if role == "DEVOPS":
        # DEVOPS רואה הכל – נשאיר manager_key = None
        manager_key = None

    elif role == "HR_LEAD":
        # ראש צוות HR – המשרות שקשורות אליו ישירות
        manager_key = user_id

    elif role in ("HR_MANAGER", "RECRUITER"):
        # גם מנהל HR וגם מגייס/ת → הולכים לטבלת users להביא את ה-manager_id שלהם
        cur.execute("SELECT manager_id FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["manager_id"]:
            manager_key = row["manager_id"]

    # עכשיו מריצים את השאילתה בהתאם
    if manager_key is not None:
        cur.execute(
            # עכשיו מריצים את השאילתה בהתאם

            """
            SELECT
                j.id,
                j.title,
                j.location,
                j.created_at,
                j.is_active,
                COUNT(jc.cv_id) AS matched_count
            FROM jobs j
            LEFT JOIN job_candidates jc
                ON jc.job_id = j.id AND jc.recruiter_status = 'מתאים'
            WHERE j.is_active = 1
            AND j.manager_id = ?
            GROUP BY j.id, j.title, j.location, j.created_at, j.is_active
            ORDER BY j.created_at DESC
            """,
    (manager_key,),
        )
    else:
        # DEVOPS (או במקרה שאין manager_id מסיבה כלשהי) → הכל
        cur.execute(

           """
            SELECT
                j.id,
                j.title,
                j.location,
                j.created_at,
                j.is_active,
                COUNT(jc.cv_id) AS matched_count
            FROM jobs j
            LEFT JOIN job_candidates jc
                ON jc.job_id = j.id AND jc.recruiter_status = 'מתאים'
            WHERE j.is_active = 1
            GROUP BY j.id, j.title, j.location, j.created_at, j.is_active
            ORDER BY j.created_at DESC
            """
            
        )

    rows = cur.fetchall()
    conn.close()

    jobs = [
        {
            "id": row["id"],
            "title": row["title"],
            "location": row["location"],
            "created_at": row["created_at"],
            "is_active": row["is_active"],
            "matched_count": row["matched_count"],
        }
        for row in rows
    ]

    return jsonify({"success": True, "jobs": jobs})


def extract_skills(text: str) -> str | None:
    if not text:
        return None

    skills_keywords = [
        "python", "java", "c++", "c#", "javascript", "typescript",
        "react", "node", "node.js", "express", "html", "css",
        "sql", "mysql", "postgresql", "mongodb",
        "docker", "kubernetes", "aws", "azure", "gcp",
        "git", "linux", "flask", "django", "fastapi",
        "tensorflow", "keras", "pandas", "numpy"
    ]

    text_lower = text.lower()
    found = []

    for skill in skills_keywords:
        if skill in text_lower and skill not in found:
            found.append(skill)

    if not found:
        return None

    return ", ".join(found)

# ----------------- פרטי משרה בודדת -----------------

@app.route("/api/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id):
    """
    מחזיר את כל פרטי המשרה לפי job_id.
    הרשאות זהות ל-/api/jobs: HR_LEAD רואה משרות שלו,
    HR_MANAGER/RECRUITER רואים משרות של המנהל שלהם, DEVOPS רואה הכל.
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    user_id = session["user_id"]
    role = session.get("role")

    conn = get_db()
    cur = conn.cursor()

    manager_key = None

    if role == "DEVOPS":
        manager_key = None

    elif role == "HR_LEAD":
        manager_key = user_id

    elif role in ("HR_MANAGER", "RECRUITER"):
        cur.execute("SELECT manager_id FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["manager_id"]:
            manager_key = row["manager_id"]
    else:
        conn.close()
        return jsonify({"success": False, "message": "אין הרשאה"}), 403

    if manager_key is not None:
        cur.execute(
            """
            SELECT id, title, description, must_requirements,
                   nice_to_have_requirements, location, employment_type,
                   work_mode, required_years_experience, salary_range,
                   closing_date, created_at, is_active, closed_at, closed_reason
            FROM jobs
            WHERE id = ? AND manager_id = ?
            """,
            (job_id, manager_key),
        )
    else:
        cur.execute(
            """
            SELECT id, title, description, must_requirements,
                   nice_to_have_requirements, location, employment_type,
                   work_mode, required_years_experience, salary_range,
                   closing_date, created_at, is_active, closed_at, closed_reason
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return jsonify({"success": False, "message": "המשרה לא נמצאה או שאין לך הרשאה אליה"}), 404

    job = {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "must_requirements": row["must_requirements"],
        "nice_to_have_requirements": row["nice_to_have_requirements"],
        "location": row["location"],
        "employment_type": row["employment_type"],
        "work_mode": row["work_mode"],
        "required_years_experience": row["required_years_experience"],
        "salary_range": row["salary_range"],
        "closing_date": row["closing_date"],
        "created_at": row["created_at"],
        "is_active": row["is_active"],
        "closed_at": row["closed_at"],
        "closed_reason": row["closed_reason"],
    }

    return jsonify({"success": True, "job": job})

# ----------------- סגירת משרה -----------------

@app.route("/api/jobs/<int:job_id>/close", methods=["POST"])
def close_job(job_id):
    """
    סוגר משרה ידנית. מקבל JSON עם שדה closed_reason (אופציונלי).
    ערכים תקינים: 'manual', 'hired'. ברירת מחדל: 'manual'.
    הרשאות: HR_LEAD, HR_MANAGER בלבד.
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    user_id = session["user_id"]
    role = session.get("role")

    if role not in ("HR_LEAD", "HR_MANAGER"):
        return jsonify({"success": False, "message": "אין הרשאה לסגור משרה"}), 403

    data = request.get_json(silent=True) or {}
    closed_reason = data.get("closed_reason", "manual")
    if closed_reason not in ("manual", "hired", "filled_internally", "canceled"):
        return jsonify({"success": False, "message": "closed_reason לא תקין. ערכים מותרים: manual, hired, filled_internally, canceled"}), 400

    conn = get_db()
    cur = conn.cursor()

    # קביעת manager_key לוידוא בעלות על המשרה
    if role == "HR_LEAD":
        manager_key = user_id
    else:
        cur.execute("SELECT manager_id FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        manager_key = row["manager_id"] if row and row["manager_id"] else None

    if manager_key is None:
        conn.close()
        return jsonify({"success": False, "message": "לא ניתן לאמת בעלות על המשרה"}), 403

    # בדיקה שהמשרה קיימת, פעילה, ושייכת למנהל הרלוונטי
    cur.execute(
        "SELECT id FROM jobs WHERE id = ? AND manager_id = ? AND is_active = 1",
        (job_id, manager_key),
    )
    if cur.fetchone() is None:
        conn.close()
        return jsonify({"success": False, "message": "המשרה לא נמצאה, כבר סגורה, או שאין לך הרשאה אליה"}), 404

    cur.execute(
        """
        UPDATE jobs
        SET is_active = 0,
            closed_at = datetime('now', 'localtime'),
            closed_reason = ?
        WHERE id = ?
        """,
        (closed_reason, job_id),
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "המשרה נסגרה בהצלחה"})

# ----------------- היסטוריית משרות סגורות -----------------

@app.route("/api/jobs/closed", methods=["GET"])
def list_closed_jobs():
    """
    מחזיר את כל המשרות הסגורות של מנהל ה-HR הרלוונטי.
    משרה נחשבת סגורה אם is_active = 0.
    הרשאות זהות ל-/api/jobs.
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    user_id = session["user_id"]
    role = session.get("role")

    conn = get_db()
    cur = conn.cursor()

    manager_key = None

    if role == "DEVOPS":
        manager_key = None

    elif role == "HR_LEAD":
        manager_key = user_id

    elif role in ("HR_MANAGER", "RECRUITER"):
        cur.execute("SELECT manager_id FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row and row["manager_id"]:
            manager_key = row["manager_id"]
    else:
        conn.close()
        return jsonify({"success": False, "message": "אין הרשאה"}), 403

    if manager_key is not None:
        cur.execute(
            """
            SELECT
                j.id,
                j.title,
                j.location,
                j.created_at,
                j.closed_at,
                j.closed_reason,
                COUNT(jc.cv_id) AS matched_count
            FROM jobs j
            LEFT JOIN job_candidates jc
                ON jc.job_id = j.id AND jc.recruiter_status = 'מתאים'
            WHERE j.is_active = 0
              AND j.manager_id = ?
            GROUP BY j.id
            ORDER BY j.closed_at DESC
            """,
            (manager_key,),
        )
    else:
        cur.execute(
            """
            SELECT
                j.id,
                j.title,
                j.location,
                j.created_at,
                j.closed_at,
                j.closed_reason,
                COUNT(jc.cv_id) AS matched_count
            FROM jobs j
            LEFT JOIN job_candidates jc
                ON jc.job_id = j.id AND jc.recruiter_status = 'מתאים'
            WHERE j.is_active = 0
            GROUP BY j.id
            ORDER BY j.closed_at DESC
            """
        )

    rows = cur.fetchall()
    conn.close()

    jobs = [
        {
            "id": row["id"],
            "title": row["title"],
            "location": row["location"],
            "created_at": row["created_at"],
            "closed_at": row["closed_at"],
            "closed_reason": row["closed_reason"],
            "matched_count": row["matched_count"],
        }
        for row in rows
    ]

    return jsonify({"success": True, "jobs": jobs})


# ----------------- רשימת מועמדים לכל משרה -----------------

@app.route("/api/jobs/<int:job_id>/candidates", methods=["GET"])
def list_job_candidates(job_id):
    """
    מחזיר רשימת מועמדים למשרה מסוימת.

    הרשאות:
    - DEVOPS → רואה את כל המשרות.
    - HR_LEAD  → רואה משרות שבהן הוא manager_id.
    - HR_MANAGER / RECRUITER → רואים משרות של המנהל שלהם (users.manager_id).
    """

    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    user_id = session["user_id"]
    role = session.get("role")

    conn = get_db()
    cur = conn.cursor()

    # קובע עבור מי מותר לראות את המשרה, בדיוק כמו ב-/api/jobs
    manager_key = None

    if role == "DEVOPS":
        manager_key = None  # DEVOPS רואה הכל

    elif role == "HR_LEAD":
        manager_key = user_id

    elif role in ("HR_MANAGER", "RECRUITER"):
        cur.execute("SELECT manager_id FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            manager_key = row["manager_id"]
    else:
        conn.close()
        return jsonify(
            {"success": False, "message": "אין לך הרשאה לצפות במועמדים למשרה"}
        ), 403

    # בודקים שהמשרה קיימת ושהיא שייכת למנהל הרלוונטי
    if manager_key is not None:
        cur.execute(
            """
            SELECT id, title, manager_id
            FROM jobs
            WHERE id = ? AND is_active = 1 AND manager_id = ?
            """,
            (job_id, manager_key),
        )
    else:
        # DEVOPS – רק לוודא שהמשרה קיימת ופעילה
        cur.execute(
            """
            SELECT id, title, manager_id
            FROM jobs
            WHERE id = ? AND is_active = 1
            """,
            (job_id,),
        )

    job_row = cur.fetchone()
    if job_row is None:
        conn.close()
        return jsonify(
            {"success": False, "message": "המשרה לא נמצאה או שאין לך הרשאה אליה"}
        ), 404

    # עכשיו מביאים את המועמדים למשרה הזו
    cur.execute(
        """
        SELECT
            jc.cv_id,
            jc.linked_at,

            c.file_path,
            c.education,
            c.professional_summary,
            jc.recruiter_status,
            jc.recruiter_feedback,
            cs.final_score,
            cs.age,
            cs.age_score,
            cs.distance_score,
            cs.must_requirements_score,
            cs.years_experience_score,
            cs.nice_to_have_score,
            cs.llm_score,
            cs.llm_flag,
            cs.llm_extracted,
            jc.human_score,
            (
                SELECT stage FROM candidate_progress_events
                WHERE job_id = jc.job_id AND cv_id = jc.cv_id AND stage IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            ) AS latest_stage
        FROM job_candidates AS jc
        LEFT JOIN candidates AS c
            ON jc.cv_id = c.cv_id
        LEFT JOIN cv_scores AS cs
            ON jc.cv_id = cs.cv_id AND jc.job_id = cs.job_id
        WHERE jc.job_id = ?
        ORDER BY jc.linked_at DESC
        """,
        (job_id,),
    )

    rows = cur.fetchall()
    conn.close()

    candidates = []
    for row in rows:
        # Parse LLM-extracted JSON (if available)
        llm_data = {}
        if row["llm_extracted"]:
            try:
                llm_data = json.loads(row["llm_extracted"])
            except Exception:
                pass

        # Regex-based fallbacks (less reliable on anonymized CVs)
        experience = None
        skills = None
        try:
            cv_text = extract_text_any(row["file_path"]) if row["file_path"] else ""
            experience = extract_estimated_experience_years(cv_text)
            skills = extract_skills(cv_text)
        except Exception:
            pass

        # LLM-extracted values take priority (clean text), DB/regex used only as fallback
        final_age        = llm_data.get("estimated_age") or row["age"]
        final_location   = llm_data.get("candidate_city")
        final_experience = llm_data.get("years_of_experience") or experience
        # Don't fall back to garbled OCR text from DB for education/summary
        final_education  = llm_data.get("education")
        final_summary    = llm_data.get("professional_summary")
        llm_skills       = llm_data.get("skills")  # list from LLM
        if llm_skills and isinstance(llm_skills, list) and llm_skills:
            final_skills = ", ".join(llm_skills)
        else:
            final_skills = skills  # regex fallback only

        candidates.append(
            {
                "cv_id": row["cv_id"],
                "id": row["cv_id"],
                "name": f"מועמד/ת {row['cv_id']}",
                "age": final_age,
                "location": final_location,
                "matchScore": row["final_score"],
                "linked_at": row["linked_at"],
                "education": final_education,
                "summary": final_summary,
                "experience": final_experience,
                "skills": final_skills,
                "recruiter_status": row["recruiter_status"],
                "recruiter_feedback": row["recruiter_feedback"],
                "human_score": row["human_score"],
                "latest_stage": row["latest_stage"],
                "llm_score": row["llm_score"],
                "llm_flag": row["llm_flag"],
                "cv_extension": os.path.splitext(row["file_path"])[1].lower() if row["file_path"] else "",

                "scores": {
                    "age_score": row["age_score"],
                    "distance_score": row["distance_score"],
                    "must_requirements_score": row["must_requirements_score"],
                    "years_experience_score": row["years_experience_score"],
                    "nice_to_have_score": row["nice_to_have_score"],
                },
            }
        )

    return jsonify(
        {
            "success": True,
            "job": {"id": job_row["id"], "title": job_row["title"]},
            "candidates": candidates,
        }
    )

# ----------------- הורדת קו"ח אנונימי -----------------

_CV_MIMETYPES = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

@app.route("/api/candidates/<int:cv_id>/cv-file", methods=["GET"])
def serve_candidate_cv(cv_id):
    """
    מחזיר את קובץ הקו"ח האנונימי של המועמד.
    ?download=1  → כפרצוף הורדה (Content-Disposition: attachment)
    ברירת מחדל  → תצוגה מוטמעת (Content-Disposition: inline)
    הרשאות: כל תפקיד מחובר (HR_LEAD, HR_MANAGER, RECRUITER, DEVOPS).
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    if session.get("role") not in ("HR_LEAD", "HR_MANAGER", "RECRUITER", "DEVOPS"):
        return jsonify({"success": False, "message": "אין הרשאה"}), 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT file_path, file_name FROM candidates WHERE cv_id = ?", (cv_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return jsonify({"success": False, "message": "מועמד לא נמצא"}), 404

    # אבטחת נתיב: ודא שהקובץ נמצא בתוך OUTPUT_DIR בלבד
    safe_path = os.path.abspath(row["file_path"])
    allowed_dir = os.path.abspath(OUTPUT_DIR)
    if not safe_path.startswith(allowed_dir + os.sep) and safe_path != allowed_dir:
        return jsonify({"success": False, "message": "נתיב קובץ לא תקין"}), 403

    if not os.path.isfile(safe_path):
        return jsonify({"success": False, "message": "קובץ הקו\"ח לא נמצא בשרת"}), 404

    file_name = row["file_name"] or f"cv_{cv_id}"
    ext = Path(safe_path).suffix.lower()
    mimetype = _CV_MIMETYPES.get(ext, "application/octet-stream")
    as_attachment = request.args.get("download") == "1"

    return send_file(
        safe_path,
        mimetype=mimetype,
        as_attachment=as_attachment,
        download_name=file_name,
    )

@app.route("/api/candidates/<int:cv_id>/cv-file-pdf", methods=["GET"])
def serve_candidate_cv_as_pdf(cv_id):
    """
    Serves the CV as PDF — converts docx to PDF if needed (cached next to original).
    Falls back to original file if conversion fails.
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401
    if session.get("role") not in ("HR_LEAD", "HR_MANAGER", "RECRUITER", "DEVOPS"):
        return jsonify({"success": False, "message": "אין הרשאה"}), 403

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT file_path, file_name FROM candidates WHERE cv_id = ?", (cv_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return jsonify({"success": False, "message": "מועמד לא נמצא"}), 404

    safe_path = os.path.abspath(row["file_path"])
    allowed_dir = os.path.abspath(OUTPUT_DIR)
    if not safe_path.startswith(allowed_dir + os.sep) and safe_path != allowed_dir:
        return jsonify({"success": False, "message": "נתיב קובץ לא תקין"}), 403

    if not os.path.isfile(safe_path):
        return jsonify({"success": False, "message": "קובץ לא נמצא"}), 404

    ext = Path(safe_path).suffix.lower()
    if ext == ".pdf":
        return send_file(safe_path, mimetype="application/pdf", as_attachment=False)

    # docx → convert to PDF (cached alongside original)
    pdf_path = safe_path[:-len(ext)] + "_converted.pdf"
    if not os.path.isfile(pdf_path):
        try:
            from docx2pdf import convert
            convert(safe_path, pdf_path)
        except Exception as e:
            print(f"[docx2pdf] conversion failed: {e}")
            # Fallback: serve original docx as download
            return send_file(safe_path,
                             mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             as_attachment=True,
                             download_name=row["file_name"] or f"cv_{cv_id}.docx")

    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


# ----------------- אירועי התקדמות מועמד -----------------

VALID_STAGES = {"phone_interview", "first_interview", "accepted", "rejected"}

@app.route("/api/jobs/<int:job_id>/candidates/<int:cv_id>/progress", methods=["POST"])
def add_progress_event(job_id, cv_id):
    """
    מוסיף אירוע התקדמות חדש למועמד במשרה.
    גוף הבקשה (JSON):
      event_type  – חובה: 'stage_change' | 'note'
      stage       – חובה אם event_type='stage_change': ערך מתוך VALID_STAGES
      note        – אופציונלי: טקסט חופשי
    הרשאות: HR_LEAD, HR_MANAGER בלבד.
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    role = session.get("role")
    if role not in ("HR_LEAD", "HR_MANAGER"):
        return jsonify({"success": False, "message": "אין הרשאה להוסיף אירוע התקדמות"}), 403

    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type")
    stage = data.get("stage")
    note = data.get("note", "").strip() if data.get("note") else None

    if event_type not in ("stage_change", "note"):
        return jsonify({"success": False, "message": "event_type לא תקין. ערכים מותרים: stage_change, note"}), 400

    if event_type == "stage_change":
        if stage not in VALID_STAGES:
            return jsonify({"success": False, "message": f"stage לא תקין. ערכים מותרים: {', '.join(sorted(VALID_STAGES))}"}), 400

    if event_type == "note" and not note:
        return jsonify({"success": False, "message": "note לא יכול להיות ריק"}), 400

    conn = get_db()
    cur = conn.cursor()

    # ודא שהמועמד אכן מקושר למשרה הזו
    cur.execute(
        "SELECT 1 FROM job_candidates WHERE job_id = ? AND cv_id = ?",
        (job_id, cv_id),
    )
    if cur.fetchone() is None:
        conn.close()
        return jsonify({"success": False, "message": "המועמד לא מקושר למשרה הזו"}), 404

    cur.execute(
        """
        INSERT INTO candidate_progress_events
            (job_id, cv_id, event_type, stage, note, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, cv_id, event_type, stage, note, session["user_id"]),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"success": True, "event_id": event_id}), 201


@app.route("/api/jobs/<int:job_id>/candidates/<int:cv_id>/progress", methods=["GET"])
def get_progress_events(job_id, cv_id):
    """
    מחזיר את כל אירועי ההתקדמות של מועמד במשרה, מהישן לחדש.
    הרשאות: HR_LEAD, HR_MANAGER.
    """
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401

    if session.get("role") not in ("HR_LEAD", "HR_MANAGER"):
        return jsonify({"success": False, "message": "אין הרשאה"}), 403

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            e.id,
            e.event_type,
            e.stage,
            e.note,
            e.created_at,
            u.email AS created_by_email
        FROM candidate_progress_events e
        LEFT JOIN users u ON u.id = e.created_by
        WHERE e.job_id = ? AND e.cv_id = ?
        ORDER BY e.created_at ASC
        """,
        (job_id, cv_id),
    )

    rows = cur.fetchall()
    conn.close()

    events = [
        {
            "id": row["id"],
            "event_type": row["event_type"],
            "stage": row["stage"],
            "note": row["note"],
            "created_at": row["created_at"],
            "created_by_email": row["created_by_email"],
        }
        for row in rows
    ]

    return jsonify({"success": True, "events": events})

# ----------------- דשבורדים לפי תפקיד -----------------

@app.route("/dashboard/hr-manager")
def hr_manager_dashboard():
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "HR_MANAGER":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל/ת HR"
    return render_template("hr_manager_dashboard.html", user_email=user_email)



@app.route("/dashboard/recruitment-manager")
def rm_dashboard():
    # אם תרצי, אפשר להוסיף כאן בדיקת תפקיד HR_LEAD
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "HR_LEAD":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל/ת גיוס"
    return render_template("hr_admin_dashboard.html", user_email=user_email)


@app.route("/dashboard/recruiter")
def recruiter_dashboard():
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "RECRUITER":
        return "אין לך הרשאה לדף הזה", 403

    user_name = session.get("email") or "מגייס/ת"
    return render_template("recruiter_dashboard.html", user_name=user_name)


@app.route("/dashboard/devops")
def devops_dashboard():
    # בדיקת התחברות
    if "user_id" not in session:
        return redirect("/")

    # בדיקת תפקיד
    if session.get("role") != "DEVOPS":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל מערכת"
    # נשים את השם בדף
    return render_template("devops_dashboard.html", user_email=user_email)


# ---------- LLM BACKGROUND SCORING ----------

def _run_llm_scoring(db_path: str, job_id: int, cv_id: int):
    """
    Runs in a background thread after CV upload.
    Calls Groq, calculates llm_score, compares with algo score,
    sets llm_flag=1 if difference > 20, then updates final_score.
    """
    try:
        from src.llm_client import extract_cv_data, calculate_llm_score
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Get job requirements and city
        job = cur.execute(
            "SELECT must_requirements, nice_to_have_requirements, location FROM jobs WHERE id=?",
            (job_id,)
        ).fetchone()
        if not job:
            return

        # Get CV file path and current algo score
        row = cur.execute(
            "SELECT c.file_path, cs.final_score FROM candidates c "
            "JOIN cv_scores cs ON cs.cv_id = c.cv_id AND cs.job_id = ? "
            "WHERE c.cv_id = ?",
            (job_id, cv_id)
        ).fetchone()
        if not row or not row["file_path"]:
            return

        cv_text = extract_text_any(row["file_path"]) or ""
        algo_score = row["final_score"] or 0.0

        # Fetch last 5 human-scored feedbacks for few-shot calibration
        examples = cur.execute("""
            SELECT jc.human_score, jc.recruiter_feedback,
                   cs.llm_score, cs.must_requirements_score, cs.years_experience_score
            FROM job_candidates jc
            JOIN cv_scores cs ON cs.job_id = jc.job_id AND cs.cv_id = jc.cv_id
            WHERE jc.human_score IS NOT NULL AND NOT (jc.job_id = ? AND jc.cv_id = ?)
            ORDER BY jc.reviewed_at DESC LIMIT 5
        """, (job_id, cv_id)).fetchall()

        if examples:
            lines = []
            for ex in examples:
                line = f"- מודל נתן {round(ex['llm_score'] or 0)}%, מגייס תיקן ל-{round(ex['human_score'])}%"
                if ex['recruiter_feedback']:
                    line += f" (סיבה: {ex['recruiter_feedback'][:60]})"
                lines.append(line)
            few_shot_context = "\n".join(lines)
        else:
            few_shot_context = ""

        # Call Groq
        extracted = extract_cv_data(
            cv_text,
            job["must_requirements"] or "",
            job["nice_to_have_requirements"] or "",
            few_shot_context=few_shot_context,
        )
        if extracted is None:
            return

        result = calculate_llm_score(extracted, job_city=job["location"])
        llm_score = result["llm_final_score"]

        # Flag if difference > 20 (warning only — LLM score is always used as final)
        llm_flag = 1 if abs(algo_score - llm_score) > 20 else 0
        new_final = llm_score

        cur.execute(
            """UPDATE cv_scores
               SET llm_score = ?, llm_flag = ?, final_score = ?, llm_extracted = ?
               WHERE job_id = ? AND cv_id = ?""",
            (llm_score, llm_flag, new_final,
             json.dumps(extracted, ensure_ascii=False),
             job_id, cv_id)
        )
        con.commit()
        con.close()
        print(f"[LLM] job={job_id} cv={cv_id} algo={algo_score} llm={llm_score} flag={llm_flag}")
    except Exception as e:
        print(f"[LLM] background scoring error: {e}")


def launch_llm_scoring(job_id: int, cv_id: int):
    t = threading.Thread(target=_run_llm_scoring, args=(DB_PATH, job_id, cv_id), daemon=True)
    t.start()


def _convert_docx_to_pdf(file_path: str):
    """Converts a docx file to PDF in the background and caches it alongside the original."""
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext != ".docx":
            return
        pdf_path = file_path[:-len(ext)] + "_converted.pdf"
        if os.path.isfile(pdf_path):
            return  # already converted
        from docx2pdf import convert
        convert(file_path, pdf_path)
        print(f"[docx2pdf] converted: {pdf_path}")
    except Exception as e:
        print(f"[docx2pdf] background conversion failed: {e}")


def launch_docx_conversion(file_path: str):
    t = threading.Thread(target=_convert_docx_to_pdf, args=(file_path,), daemon=True)
    t.start()


@app.route("/api/jobs/<int:job_id>/candidates/<int:cv_id>/reanalyze", methods=["POST"])
def reanalyze_candidate(job_id, cv_id):
    """Re-trigger LLM scoring for an existing candidate (e.g. uploaded before LLM was added)."""
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר"}), 401
    launch_llm_scoring(job_id, cv_id)
    return jsonify({"success": True, "message": "הניתוח התחיל ברקע"})


@app.route("/devops/upload-cv", methods=["GET", "POST"])
def devops_upload_cv():
    # בדיקת התחברות והרשאות כמו בדשבורד
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "DEVOPS":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל מערכת"

    conn = get_db()
    cur = conn.cursor()

    if request.method == "GET":
        # להביא רשימת משרות בשביל ה-select
        cur.execute(
            "SELECT id, title FROM jobs WHERE is_active = 1 ORDER BY created_at DESC"
        )
        jobs = cur.fetchall()
        conn.close()
        # נרנדר טמפלט חדש שניצור עוד רגע
        return render_template(
            "upload_cv.html",
            user_email=user_email,
            jobs=jobs,
        )

    # ----- POST: טיפול בהעלאת הקובץ -----
    job_id = int(request.form.get("job_id"))
    file = request.files.get("cv_file")

    # ולידציה בסיסית
    if not job_id or not file or file.filename == "":
        conn.close()
        return "חובה לבחור משרה ולהעלות קובץ", 400

    # בדיקת פורמט
    orig_ext = Path(file.filename).suffix.lower()
    if not allowed_file(file.filename):
        conn.close()
        return "מותר להעלות רק קבצי PDF או DOCX", 400
    # מייצרים שם "נקי" חדש, שלא תלוי בעברית
    safe_stem = secure_filename(Path(file.filename).stem)
    if not safe_stem:  # במקרה שכל השם היה בעברית ונמחק
        safe_stem = uuid4().hex

    filename = f"{safe_stem}{orig_ext}"
    # שמירה ל-input
    
    in_path = os.path.join(INPUT_DIR, filename)
    file.save(in_path)

    # יצירת שם לקובץ האנונימי
    base, ext = os.path.splitext(filename)
    anon_filename = f"{base}__anon{ext}"
    out_path = os.path.join(OUTPUT_DIR, anon_filename)

    # הרצת האנונימיזר
    try:
        if ext.lower() == ".pdf":
            anonymize_pdf_file(in_path, out_path)
        else:  # .docx
            anonymize_docx_file(in_path, out_path)
    except Exception as e:
        conn.close()
        print("ERROR anonymizing:", e)
        traceback.print_exc()  # ידפיס stack trace מלא בטרמינל
        return f"שגיאה בתהליך האנונימיזציה: {e}", 500
    # רישום בקנדידייטס (משתמשת בפונקציה מה-db.py)
    try:
        cv_id = upsert_candidate(conn, out_path)
    except Exception as e:
        conn.close()
        print("ERROR upserting candidate:", e)
        return "שגיאה בשמירת המועמד במסד הנתונים", 500
        # ---------- AGE SCORING ----------
    try:
        text = extract_text_any(out_path) or ""

        birth_year, reason = infer_birth_year_simple(text)
        age = age_from_birth_year(birth_year)

        base_score = 100.0
        penalty = apply_age_penalty(base_score, age)

        if age is None or age <= 50:
            age_score_points = 10.0
        else:
            age_score_points = 0.0

        dbutil.upsert_age_score(
            conn,
            job_id,
            cv_id,
            age_score=age_score_points,
            birth_year=birth_year,
            age=age,
            reason=reason,
            confidence="N/A",
            factor=penalty["factor"],
        )
    except Exception as e:
        print("AGE SCORING ERROR (devops_upload_cv):", e)
    # לא מפיל את ההעלאה – ממשיכים הלאה
        # ---------- REQUIREMENTS SCORING (must / nice-to-have) ----------
    try:
        # 1. נביא את הדרישות של המשרה מה-DB
        cur.execute(
            """
            SELECT must_requirements, nice_to_have_requirements
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        job_row = cur.fetchone()

        if job_row:
            must_txt = job_row["must_requirements"] or ""
            nice_txt = job_row["nice_to_have_requirements"] or ""

            # 2. טקסט מתוך ה-CV האנונימי
            cv_text = extract_text_any(out_path) or ""

            # 3) חישוב נקודות דרישות לפי המשקלים שלך
            req = requirements_points(cv_text, must_txt, nice_txt)

            must_score = req["must"]["points"]          # 0–40
            nice_score = req["nice"]["points"]          # 0–10 (או 0 אם אין nice)

            # 4. עדכון טבלת הציונים (cv_scores)
            cur.execute(
                """
                UPDATE cv_scores
                SET must_requirements_score = ?,
                    nice_to_have_score     = ?
                WHERE cv_id = ? AND job_id = ?
                """,
                (must_score, nice_score, cv_id, job_id),
            )
            conn.commit()
            dbutil.recompute_final_score(conn, job_id, cv_id)
    except Exception as e:
        print("REQ SCORING ERROR (devops_upload_cv):", e)
        # לא מפיל את הבקשה – פשוט אין ציונים לדרישות
    # ---------- YEARS EXPERIENCE SCORING ----------
    try:
        cur.execute(
            """
            SELECT title, description, must_requirements, nice_to_have_requirements, required_years_experience
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        job_row = cur.fetchone()

        if job_row:
            job_text = " ".join([
                job_row["title"] or "",
                job_row["description"] or "",
                job_row["must_requirements"] or "",
                job_row["nice_to_have_requirements"] or "",
            ])

            cv_text = extract_text_any(out_path) or ""

            required_years = job_row["required_years_experience"]
            if required_years is None:
                required_years = extract_required_years_from_job_text(job_text)            
            candidate_years = extract_relevant_experience_years(cv_text, job_text)
            years_score = calculate_years_experience_score(candidate_years, required_years)

            cur.execute(
                """
                UPDATE cv_scores
                SET years_experience_score = ?
                WHERE cv_id = ? AND job_id = ?
                """,
                (years_score, cv_id, job_id),
            )
            conn.commit()
            dbutil.recompute_final_score(conn, job_id, cv_id)

            print("YEARS DEBUG:", {
                "required_years": required_years,
                "candidate_years": candidate_years,
                "years_score": years_score,
            })
    except Exception as e:
        print("YEARS SCORING ERROR (devops_upload_cv):", e)
    
    # ---------- DISTANCE SCORING ----------
    try:
        cur.execute(
            """
            SELECT location, work_mode
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        job_row = cur.fetchone()

        if job_row:
            job_city = job_row["location"] or ""
            work_mode = job_row["work_mode"] or ""
            cv_text = extract_text_any(out_path) or ""

            candidate_city = extract_candidate_city(cv_text)
            distance_km = calculate_distance_km(candidate_city, job_city) if candidate_city else None
            distance_score = calculate_distance_score(distance_km)

            if work_mode == "עבודה מהבית":
                distance_score = 10.0
            elif work_mode == "היברידי":
                if distance_score is None:
                    distance_score = 10.0
                else:
                    distance_score = max(distance_score, 5.0)

            cur.execute(
                """
                UPDATE cv_scores
                SET distance_score = ?
                WHERE cv_id = ? AND job_id = ?
                """,
                (distance_score, cv_id, job_id),
            )
            conn.commit()
            dbutil.recompute_final_score(conn, job_id, cv_id)

            print("DISTANCE DEBUG:", {
                "job_city": job_city,
                "work_mode": work_mode,
                "candidate_city": candidate_city,
                "distance_km": distance_km,
                "distance_score": distance_score,
            })
    except Exception as e:
        print("DISTANCE SCORING ERROR (devops_upload_cv):", e)
    
    # קישור למשרה בטבלת job_candidates
    try:
        cur.execute(
            """
            INSERT OR IGNORE INTO job_candidates (job_id, cv_id)
            VALUES (?, ?)
            """,
            (job_id, cv_id),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        print("ERROR linking job_candidate:", e)
        return "שגיאה בקישור קו\"ח למשרה", 500

    conn.close()

    launch_docx_conversion(out_path)
    launch_llm_scoring(job_id, cv_id)
    return redirect("/dashboard/devops")

# ----------------- LOGOUT -----------------

@app.route("/logout")
def logout():
    """
    התנתקות – מנקה את ה-session ומחזיר לדף ההתחברות
    """
    session.clear()
    return redirect("/")


# ----------------- העלאת קוח -----------------

@app.route("/api/upload_cv", methods=["POST"])
def upload_cv():
    """
    העלאת קו\"ח + אנונימיזציה + רישום למועמד וקישור למשרה.
    ציפיה ל-form-data:
      - job_id  (id של המשרה)
      - file    (קובץ PDF / DOCX)
    """

    # חייב להיות מחובר ומשתמש DEVOPS
    if "user_id" not in session:
        return jsonify({"success": False, "message": "לא מחובר/ת"}), 401

    if session.get("role") != "DEVOPS":
        return jsonify({"success": False, "message": "אין לך הרשאה לפעולה הזו"}), 403

    # קלט מהטופס
    job_id_raw = request.form.get("job_id")
    file = request.files.get("file")

    if not job_id_raw:
        return jsonify({"success": False, "message": "חובה לבחור משרה"}), 400

    try:
        job_id = int(job_id_raw)
    except ValueError:
        return jsonify({"success": False, "message": "job_id לא תקין"}), 400

    if not file or file.filename == "":
        return jsonify({"success": False, "message": "לא התקבל קובץ קו\"ח"}), 400

    # פתיחת חיבור ל-DB דרך ה-SCHEMA של cv_macher (candidates+cv_scores+job_candidates)
    con = cv_connect(DB_PATH)
    cur = con.cursor()

    # לוודא שהמשרה קיימת ופעילה
    cur.execute("SELECT id FROM jobs WHERE id = ? AND is_active = 1", (job_id,))
    if cur.fetchone() is None:
        con.close()
        return jsonify({"success": False, "message": "המשרה לא קיימת או לא פעילה"}), 400

    # שמירת הקובץ לתיקיית input
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    original_name = secure_filename(file.filename)
    ext = Path(original_name).suffix.lower()

    if ext not in [".pdf", ".docx"]:
        con.close()
        return jsonify({
            "success": False,
            "message": "מותר להעלות רק קבצי PDF או DOCX"
        }), 400

    unique_name = f"{uuid4().hex}{ext}"
    input_path = str(Path(INPUT_DIR) / unique_name)
    output_path = str(Path(OUTPUT_DIR) / unique_name)

    # שמירה לדיסק
    file.save(input_path)

    # הרצת האנונימיזציה
    try:
        if ext == ".pdf":
            anonymize_pdf_file(input_path, output_path)
        else:
            anonymize_docx_file(input_path, output_path)
    except Exception as e:
        con.close()
        return jsonify({
            "success": False,
            "message": f"שגיאה בעיבוד הקובץ: {e}"
        }), 500

    # רישום המועמד בטבלת candidates (ה־file_path הוא של הקובץ האנונימי!)
    cv_id = upsert_candidate(con, output_path)
    # ---------- AGE SCORING ----------
    try:
        # 1. חילוץ טקסט מהקובץ האנונימי (DOCX/PDF)
        text = extract_text_any(output_path) or ""

        # 2. זיהוי שנת לידה → גיל
        birth_year, reason = infer_birth_year_simple(text)
        age = age_from_birth_year(birth_year)

        # 3. ענישת גיל על בסיס 0–100 (לשקיפות + factor)
        base_score = 100.0
        penalty = apply_age_penalty(base_score, age)

        # 4. תרגום לגייד’גט 0–10 כמו ב-run_scoring.py
        if age is None or age <= 50:
            age_score_points = 10.0
        else:
            age_score_points = 0.0

        # 5. שמירה לטבלת cv_scores דרך upsert_age_score
        dbutil.upsert_age_score(
            con,
            int(job_id),
            cv_id,
            age_score=age_score_points,
            birth_year=birth_year,
            age=age,
            reason=reason,
            confidence="N/A",
            factor=penalty["factor"],
        )
    except Exception as e:
        print("AGE SCORING ERROR:", e)
        # לא מפילים את כל הבקשה – פשוט נמשיך בלי age_score

    # קישור בין המשרה לבין הקו\"ח בטבלה job_candidates
    cur.execute(
        """
        INSERT INTO job_candidates (job_id, cv_id, linked_at)
        VALUES (?, ?, datetime('now','localtime'))
        """,
        (job_id, cv_id),
    )
        # ---------- REQUIREMENTS SCORING (must / nice-to-have) ----------
    try:
        # 1. נביא את הדרישות של המשרה
        cur.execute(
            """
            SELECT must_requirements, nice_to_have_requirements
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        job_row = cur.fetchone()

        if job_row:
            must_txt = job_row["must_requirements"] or ""
            nice_txt = job_row["nice_to_have_requirements"] or ""

            # 2. טקסט מהקובץ האנונימי
            cv_text = extract_text_any(output_path) or ""

            # 3. חישוב ציונים
            req = requirements_points(cv_text, must_txt, nice_txt)
            must_score = req["must"]["points"]   # 0–40
            nice_score = req["nice"]["points"]   # 0–10 (10 אם אין nice)


            # 4. עדכון cv_scores
            cur.execute(
                """
                UPDATE cv_scores
                SET must_requirements_score = ?,
                    nice_to_have_score     = ?
                WHERE cv_id = ? AND job_id = ?
                """,
                (must_score, nice_score, cv_id, job_id),
            )
            dbutil.recompute_final_score(con, int(job_id), int(cv_id))
    except Exception as e:
        print("REQ SCORING ERROR (/api/upload_cv):", e)
    # ---------- YEARS EXPERIENCE SCORING ----------
    try:
        cur.execute(
            """
            SELECT title, description, must_requirements, nice_to_have_requirements, required_years_experience
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        job_row = cur.fetchone()

        if job_row:
            job_text = " ".join([
                job_row["title"] or "",
                job_row["description"] or "",
                job_row["must_requirements"] or "",
                job_row["nice_to_have_requirements"] or "",
            ])

            cv_text = extract_text_any(output_path) or ""

            required_years = extract_required_years_from_job_text(job_text)
            if required_years is None:
                required_years = extract_required_years_from_job_text(job_text)
            candidate_years = extract_relevant_experience_years(cv_text, job_text)
            years_score = calculate_years_experience_score(candidate_years, required_years)

            cur.execute(
                """
                UPDATE cv_scores
                SET years_experience_score = ?
                WHERE cv_id = ? AND job_id = ?
                """,
                (years_score, cv_id, job_id),
            )
            dbutil.recompute_final_score(con, int(job_id), int(cv_id))

            print("YEARS DEBUG:", {
                "required_years": required_years,
                "candidate_years": candidate_years,
                "years_score": years_score,
            })
    except Exception as e:
        print("YEARS SCORING ERROR (/api/upload_cv):", e)
    
    # ---------- DISTANCE SCORING ----------
    try:
        cur.execute(
            """
            SELECT location, work_mode
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        )
        job_row = cur.fetchone()

        if job_row:
            job_city = job_row["location"] or ""
            work_mode = job_row["work_mode"] or ""
            cv_text = extract_text_any(output_path) or ""

            candidate_city = extract_candidate_city(cv_text)
            distance_km = calculate_distance_km(candidate_city, job_city) if candidate_city else None
            distance_score = calculate_distance_score(distance_km)

            if work_mode == "עבודה מהבית":
                distance_score = 10.0
            elif work_mode == "היברידי":
                if distance_score is None:
                    distance_score = 10.0
                else:
                    distance_score = max(distance_score, 5.0)

            cur.execute(
                """
                UPDATE cv_scores
                SET distance_score = ?
                WHERE cv_id = ? AND job_id = ?
                """,
                (distance_score, cv_id, job_id),
            )
            dbutil.recompute_final_score(con, int(job_id), int(cv_id))

            print("DISTANCE DEBUG:", {
                "job_city": job_city,
                "work_mode": work_mode,
                "candidate_city": candidate_city,
                "distance_km": distance_km,
                "distance_score": distance_score,
            })
    except Exception as e:
        print("DISTANCE SCORING ERROR (/api/upload_cv):", e)
    
    con.commit()
    con.close()

    launch_docx_conversion(output_path)
    launch_llm_scoring(int(job_id), int(cv_id))
    return jsonify({
        "success": True,
        "message": "קו\"ח הועלו, עברו אנונימיזציה ונקשרו למשרה בהצלחה",
        "cv_id": cv_id,
        "job_id": job_id,
    }), 201

# ----------------- DB פונקציות -----------------
# -----------------helper להרשאות DevOps בלבד -----------------

def devops_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "message": "לא מחובר/ת"}), 401
        if session.get("role") != "DEVOPS":
            return jsonify({"success": False, "message": "אין לך הרשאה לפעולה הזו"}), 403
        return f(*args, **kwargs)
    return wrapper


# ----------------החזרת רשימת משתמשי הצוות של מנהל ה-HR -----------------
@app.route("/api/hr/team-users", methods=["GET"])
@hr_manager_required
def api_hr_team_users():
    manager_id = session["user_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, email, role, company_name
        FROM users
        WHERE manager_id = ?
          AND is_approved = 1
          AND role IN ('HR_MANAGER', 'RECRUITER')
        ORDER BY id DESC
        """,
        (manager_id,),
    )
    rows = cur.fetchall()
    conn.close()

    users = [
        {
            "id": row["id"],
            "email": row["email"],
            "role": row["role"],
            "company_name": row["company_name"],
        }
        for row in rows
    ]

    return jsonify({"success": True, "users": users})
# ----------------POST: יצירת משתמש צוות חדש ע"י מנהל HR -----------------
@app.route("/api/hr/team-users", methods=["POST"])
@hr_manager_required
def api_hr_create_team_user():
    data = request.get_json() or {}

    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "").strip().upper()
    password = (data.get("password") or "").strip()

    # ולידציה בסיסית
    if not email or not role or not password:
        return jsonify({
            "success": False,
            "message": "חובה למלא אימייל, תפקיד וסיסמה זמנית"
        }), 400

    if role not in ("HR_MANAGER", "RECRUITER"):
        return jsonify({
            "success": False,
            "message": "ניתן ליצור רק HR_MANAGER או RECRUITER"
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "הסיסמה חייבת להיות באורך 6 תווים לפחות"
        }), 400

    manager_id = session["user_id"]

    conn = get_db()
    cur = conn.cursor()

    # מביאים את שם החברה של המנהל HR – כדי שכל הצוות יהיה על אותה חברה
    cur.execute("SELECT company_name FROM users WHERE id = ?", (manager_id,))
    manager_row = cur.fetchone()
    if not manager_row:
        conn.close()
        return jsonify({
            "success": False,
            "message": "לא נמצא מנהל HR המחובר"
        }), 500

    company_name = manager_row["company_name"]

    # בדיקה אם האימייל כבר קיים
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cur.fetchone() is not None:
        conn.close()
        return jsonify({
            "success": False,
            "message": "אימייל זה כבר רשום במערכת"
        }), 400

    password_hash = generate_password_hash(password)

    try:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, role, company_name, is_approved, manager_id)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (email, password_hash, role, company_name, manager_id),
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "success": True,
        "message": "משתמש צוות חדש נוצר בהצלחה",
        "user_id": new_id,
        "email": email,
        "role": role,
        "company_name": company_name
    }), 201

# -----------------API: סטטיסטיקות כלליות לדשבורד DevOps-----------------

@app.route("/api/admin/stats", methods=["GET"])
@devops_required
def api_admin_stats():
    """מחזיר ספירת משתמשים ממתינים ופעילים לדשבורד ה-DevOps."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE is_approved = 0")
    pending = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM users
        WHERE is_approved = 1
          AND last_login >= datetime('now', '-30 days')
    """)
    active = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1")
    active_jobs = cur.fetchone()[0]
    conn.close()
    return jsonify({
        "success": True,
        "pending_users": pending,
        "active_users": active,
        "active_jobs": active_jobs,
    })


# -----------------API: רשימת משתמשים ממתינים לאישור-----------------

@app.route("/api/admin/pending-users", methods=["GET"])
@devops_required
def api_pending_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, company_name, role, is_approved
        FROM users
        WHERE is_approved = 0
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    conn.close()

    users = [
        {
            "id": row["id"],
            "email": row["email"],
            "company_name": row["company_name"],
            "role": row["role"],
        }
        for row in rows
    ]

    return jsonify({"success": True, "users": users})
# -----------------API: אישור / דחייה -----------------

@app.route("/api/admin/users/<int:user_id>/approve", methods=["POST"])
@devops_required
def api_approve_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    user_row = cur.fetchone()
    if user_row is None:
        conn.close()
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 404
    user_email = user_row["email"]
    cur.execute("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    log_event(f"User approved: {user_email}", "success", session.get("user_id"))
    return jsonify({"success": True, "message": "המשתמש אושר בהצלחה"})


@app.route("/api/admin/users/<int:user_id>/reject", methods=["POST"])
@devops_required
def api_reject_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    user_row = cur.fetchone()
    if user_row is None:
        conn.close()
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 404
    user_email = user_row["email"]
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    log_event(f"User rejected: {user_email}", "warning", session.get("user_id"))
    return jsonify({"success": True, "message": "בקשת המשתמש נדחתה ונמחקה"})


# -----------------API: לוג מערכת לדשבורד DevOps-----------------

@app.route("/api/admin/logs", methods=["GET"])
@devops_required
def api_admin_logs():
    """מחזיר 50 האירועים האחרונים מלוג המערכת."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, event_type, message, user_id, created_at
        FROM system_logs
        ORDER BY created_at DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()
    logs = [
        {
            "id":        row["id"],
            "type":      row["event_type"],
            "message":   row["message"],
            "timestamp": row["created_at"],
        }
        for row in rows
    ]
    return jsonify({"success": True, "logs": logs})


# -----------------API: פידבקים ממגייסים לדשבורד DevOps-----------------

@app.route("/api/admin/feedback", methods=["GET"])
@devops_required
def api_admin_feedback():
    """
    מחזיר את כל פידבקי המגייסים (recruiter review) לדשבורד ה-DevOps.
    כולל שם משרה, חברה, מייל המגייס, סטטוס ותוכן הפידבק.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            jc.job_id,
            jc.cv_id,
            jc.recruiter_status,
            jc.recruiter_feedback,
            jc.reviewed_at,
            j.title          AS job_title,
            u_rev.email      AS reviewer_email,
            u_mgr.company_name AS company
        FROM job_candidates jc
        JOIN jobs j           ON jc.job_id = j.id
        JOIN users u_rev      ON jc.reviewed_by_user_id = u_rev.id
        LEFT JOIN users u_mgr ON j.manager_id = u_mgr.id
        WHERE jc.reviewed_by_user_id IS NOT NULL
        ORDER BY jc.reviewed_at DESC
    """)
    rows = cur.fetchall()
    conn.close()

    feedbacks = [
        {
            "job_id":         row["job_id"],
            "cv_id":          row["cv_id"],
            "job_title":      row["job_title"] or "",
            "company":        row["company"] or "",
            "reviewer_email": row["reviewer_email"] or "",
            "status":         row["recruiter_status"] or "",
            "feedback":       row["recruiter_feedback"] or "",
            "reviewed_at":    row["reviewed_at"] or "",
        }
        for row in rows
    ]

    return jsonify({"success": True, "feedbacks": feedbacks, "total": len(feedbacks)})


def get_db():
    conn = dbutil.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_event(message: str, event_type: str = "info", user_id: int = None):
    """רושם אירוע ללוג המערכת. event_type: info | success | warning | error"""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO system_logs (event_type, message, user_id) VALUES (?, ?, ?)",
            (event_type, message, user_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"log_event error: {e}")


def init_db():
    """יוצר טבלת משתמשים ומוסיף 4 משתמשי דמו אם עדיין לא קיימים."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            company_name TEXT,
            is_approved INTEGER NOT NULL DEFAULT 0,
            manager_id INTEGER,
            last_login TEXT,
            FOREIGN KEY (manager_id) REFERENCES users(id)
        )
        """
    )

    # ---------- טבלת קישור בין משרות לקו"ח ----------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS job_candidates (
            job_id                 INTEGER NOT NULL,
            cv_id                  INTEGER NOT NULL,
            linked_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            recruiter_status       TEXT,
            recruiter_feedback     TEXT,
            reviewed_by_user_id    INTEGER,
            reviewed_at            TEXT,
            PRIMARY KEY (job_id, cv_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id),
            FOREIGN KEY(cv_id)  REFERENCES candidates(cv_id)
        )
        """
    )

    # ---------- טבלת משרות ----------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        must_requirements TEXT NOT NULL,
        nice_to_have_requirements TEXT,
        location TEXT,
        employment_type TEXT,
        work_mode TEXT,
        required_years_experience REAL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        is_active INTEGER NOT NULL DEFAULT 1,
        manager_id INTEGER NOT NULL
        )
        """
    )

    # --- migration: add closing/salary columns to jobs if missing ---
    jobs_cols = {row[1] for row in cur.execute("PRAGMA table_info(jobs)").fetchall()}
    jobs_missing = []
    if "closing_date" not in jobs_cols:
        jobs_missing.append(("closing_date", "TEXT"))
    if "salary_range" not in jobs_cols:
        jobs_missing.append(("salary_range", "TEXT"))
    if "closed_at" not in jobs_cols:
        jobs_missing.append(("closed_at", "TEXT"))
    if "closed_reason" not in jobs_cols:
        jobs_missing.append(("closed_reason", "TEXT"))
    for col_name, col_type in jobs_missing:
        cur.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")

    # --- migration: add recruiter review columns to job_candidates if missing ---
    jc_cols = {row[1] for row in cur.execute("PRAGMA table_info(job_candidates)").fetchall()}
    jc_missing = []
    if "recruiter_status" not in jc_cols:
        jc_missing.append(("recruiter_status", "TEXT"))
    if "recruiter_feedback" not in jc_cols:
        jc_missing.append(("recruiter_feedback", "TEXT"))
    if "reviewed_by_user_id" not in jc_cols:
        jc_missing.append(("reviewed_by_user_id", "INTEGER"))
    if "reviewed_at" not in jc_cols:
        jc_missing.append(("reviewed_at", "TEXT"))
    if "human_score" not in jc_cols:
        jc_missing.append(("human_score", "REAL"))
    for col_name, col_type in jc_missing:
        cur.execute(f"ALTER TABLE job_candidates ADD COLUMN {col_name} {col_type}")

    # --- migration: add llm columns to cv_scores if missing ---
    cs_cols = {row[1] for row in cur.execute("PRAGMA table_info(cv_scores)").fetchall()}
    if "llm_score" not in cs_cols:
        cur.execute("ALTER TABLE cv_scores ADD COLUMN llm_score REAL")
    if "llm_flag" not in cs_cols:
        cur.execute("ALTER TABLE cv_scores ADD COLUMN llm_flag INTEGER DEFAULT 0")
    if "llm_extracted" not in cs_cols:
        cur.execute("ALTER TABLE cv_scores ADD COLUMN llm_extracted TEXT")

    # --- migration: add last_login to users if missing ---
    u_cols = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
    if "last_login" not in u_cols:
        cur.execute("ALTER TABLE users ADD COLUMN last_login TEXT")

    # ---------- טבלת לוג מערכת ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            message    TEXT NOT NULL,
            user_id    INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    # ---------- טבלת היסטוריית התקדמות מועמדים ----------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidate_progress_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id      INTEGER NOT NULL,
            cv_id       INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            stage       TEXT,
            note        TEXT,
            created_by  INTEGER,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(job_id)     REFERENCES jobs(id),
            FOREIGN KEY(cv_id)      REFERENCES candidates(cv_id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    """)

        # 4 משתמשי דמו
    demo_users = [
        ("hr_manager@example.com", "123456", "HR_MANAGER", "Demo Company HR"),
        ("hr_lead@example.com", "123456", "HR_LEAD", "Demo Company HR"),
        ("recruiter@example.com", "123456", "RECRUITER", "Demo Company HR"),
        ("devops@example.com", "123456", "DEVOPS", "Platform Admin"),
    ]

    # קודם נוודא שה-HR_MANAGER קיים ונקבל את ה-id שלו
    cur.execute("SELECT id FROM users WHERE email = ?", ("hr_manager@example.com",))
    row = cur.fetchone()
    if row is None:
        pwd_hash = generate_password_hash("123456")
        cur.execute(
            """
            INSERT INTO users (email, password_hash, role, company_name, is_approved, manager_id)
            VALUES (?, ?, ?, ?, 1, NULL)
            """,
            ("hr_manager@example.com", pwd_hash, "HR_MANAGER", "Demo Company HR"),
        )
        hr_manager_id = cur.lastrowid
    else:
        hr_manager_id = row["id"]

    # עכשיו נוסיף את שאר המשתמשים (HR_LEAD, RECRUITER, DEVOPS)
    other_demo_users = [
        ("hr_lead@example.com", "123456", "HR_LEAD", "Demo Company HR", hr_manager_id),
        ("recruiter@example.com", "123456", "RECRUITER", "Demo Company HR", hr_manager_id),
        ("devops@example.com", "123456", "DEVOPS", "Platform Admin", None),
    ]

    for email, plain_pwd, role, company_name, manager_id in other_demo_users:
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone() is None:
            pwd_hash = generate_password_hash(plain_pwd)
            cur.execute(
                """
                INSERT INTO users (email, password_hash, role, company_name, is_approved, manager_id)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (email, pwd_hash, role, company_name, manager_id),
            )

    conn.commit()
    conn.close()
    print("✅ DB Ready – cv_matcher.db מוכן (users + jobs)")

# ----------------- LOGIN API -----------------

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON body"}), 400

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"success": False, "message": "חסר אימייל או סיסמה"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        log_event(f"ניסיון התחברות כושל – אימייל לא קיים: {email}", "warning")
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 401

    if not check_password_hash(row["password_hash"], password):
        log_event(f"ניסיון התחברות כושל – סיסמה שגויה: {email}", "warning", row["id"])
        return jsonify({"success": False, "message": "סיסמה שגויה"}), 401

    if not row["is_approved"]:
        log_event(f"ניסיון התחברות לחשבון ממתין לאישור: {email}", "warning", row["id"])
        return jsonify({
                "success": False,
            "message": "החשבון שלך עדיין ממתין לאישור מנהל המערכת"
        }), 403

    # עדכון זמן התחברות אחרון
    conn = get_db()
    conn.execute(
        "UPDATE users SET last_login = datetime('now','localtime') WHERE id = ?",
        (row["id"],)
    )
    conn.commit()
    conn.close()

    if row["role"] != "DEVOPS":
        log_event(f"התחברות מוצלחת: {email}", "success", row["id"])

    # שומרים בסשן
    session["user_id"] = row["id"]
    session["email"] = row["email"]
    session["role"] = row["role"]

    role = row["role"]

    redirect_map = {
        "HR_MANAGER": "/dashboard/hr-manager",
        "HR_LEAD": "/dashboard/recruitment-manager",
        "RECRUITER": "/dashboard/recruiter",
        "DEVOPS": "/dashboard/devops",
    }

    return jsonify(
        {
            "success": True,
            "message": "התחברת בהצלחה",
            "role": role,
            "redirect_url": redirect_map.get(role, "/"),
        }
    )


# ----------------- MAIN -----------------

if __name__ == "__main__":
    init_db()

    print("📂 משתמש בקובץ DB:", DB_PATH)
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=False)
