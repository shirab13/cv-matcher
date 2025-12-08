# auth_server.py
import os
import sqlite3
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

from flask import (
    Flask,
    request,
    jsonify,
    session,
    redirect,
    render_template,
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

# איפה נשמור את הקו"ח הגולמי ואת הקובץ האנונימי
INPUT_DIR = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\input"
OUTPUT_DIR = r"C:\Users\shira\OneDrive\Desktop\cv-matcher\output"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
app = Flask(__name__)
app.secret_key = "dev-secret-change-me"   # להחליף בסוד אמיתי בפרודקשן
CORS(app)
def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


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


# -----------------קליטת משרה חדשה-----------------

@app.route("/api/jobs", methods=["POST"])
def create_job():
    """
    יצירת משרה חדשה ב־DB.
    שדות חובה:
      - title
      - description
      - must_requirements
    שדות אופציונליים:
      - nice_to_have_requirements
      - location
      - employment_type
    """
    data = request.get_json() or {}

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    must_req = (data.get("must_requirements") or "").strip()
    nice_req = (data.get("nice_to_have_requirements") or "").strip() or None
    location = (data.get("location") or "").strip() or None
    employment_type = (data.get("employment_type") or "").strip() or None

    # ולידציה בסיסית
    if not title or not description or not must_req:
        return jsonify({
            "success": False,
            "message": "חובה למלא שם משרה, תיאור ודרישות חובה"
        }), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO jobs (
            title, description, must_requirements,
            nice_to_have_requirements, location, employment_type
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (title, description, must_req, nice_req, location, employment_type),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "המשרה נוצרה בהצלחה",
        "job_id": job_id
    }), 201
# -----------------רשימת משרות קיימות-----------------
@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    """
    מחזיר רשימת משרות פעילות לדשבורד:
    id, title, location, created_at
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, location, created_at
        FROM jobs
        WHERE is_active = 1
        ORDER BY created_at DESC
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
        }
        for row in rows
    ]

    return jsonify({"success": True, "jobs": jobs})

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
    job_id = request.form.get("job_id")
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
            cv_id,
            age_score=age_score_points,
            birth_year=birth_year,
            age=age,
            reason=reason,
            confidence="N/A",
            factor=penalty["factor"],
            final_score=None,
        )
    except Exception as e:
        print("AGE SCORING ERROR (devops_upload_cv):", e)
    # לא מפיל את ההעלאה – ממשיכים הלאה

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

    # TODO: אפשר להכניס פה גם טריגר להרצת סקורינג בהמשך
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
            cv_id,
            age_score=age_score_points,
            birth_year=birth_year,
            age=age,
            reason=reason,
            confidence="N/A",
            factor=penalty["factor"],
            final_score=None,   # את הסקור הסופי המשולב תוסיפי בעתיד אם תרצי
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
    con.commit()
    con.close()

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
    cur.execute("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 404
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "המשתמש אושר בהצלחה"})


@app.route("/api/admin/users/<int:user_id>/reject", methods=["POST"])
@devops_required
def api_reject_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    # אפשר למחוק לגמרי, או לסמן כ-rejected עם עמודה נוספת – כרגע נמחק:
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 404
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "בקשת המשתמש נדחתה ונמחקה"})


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
            FOREIGN KEY (manager_id) REFERENCES users(id)
        )
        """
    )

    # ---------- טבלת קישור בין משרות לקו"ח ----------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS job_candidates (
            job_id     INTEGER NOT NULL,
            cv_id      INTEGER NOT NULL,
            linked_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
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
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )

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
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 401

    if not check_password_hash(row["password_hash"], password):
        return jsonify({"success": False, "message": "סיסמה שגויה"}), 401
    
    if not row["is_approved"]:
        return jsonify({
                "success": False,
            "message": "החשבון שלך עדיין ממתין לאישור מנהל המערכת"
        }), 403

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
    app.run(host="127.0.0.1", port=5000, debug=True)
