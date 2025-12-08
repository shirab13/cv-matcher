# src/utils/db.py
import os, sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candidates (
  cv_id      INTEGER PRIMARY KEY AUTOINCREMENT,               -- מזהה רץ: 1,2,3...
  file_path  TEXT NOT NULL UNIQUE,
  file_name  TEXT,
  added_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))  -- זמן אנושי אוטומטי
);

CREATE TABLE IF NOT EXISTS cv_scores (
  cv_id                         INTEGER PRIMARY KEY,          -- זהה ל-candidates.cv_id
  -- סעיפי סקורינג
  age_score                     REAL,
  distance_score                REAL,
  must_requirements_score       REAL,
  years_experience_score        REAL,
  nice_to_have_score            REAL,
  final_score                   REAL,

  -- מידע נוסף על גיל
  birth_year                    INTEGER,
  age                           INTEGER,
  age_reason                    TEXT,
  age_confidence                TEXT,
  age_factor                    REAL,

  updated_at                    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  FOREIGN KEY(cv_id) REFERENCES candidates(cv_id)
);

"""


def connect(db_path: str) -> sqlite3.Connection:
    """פותח חיבור למסד הנתונים ויוצר טבלאות אם חסרות."""
    Path(os.path.dirname(db_path) or ".").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.executescript(SCHEMA)
    return con

def upsert_candidate(con: sqlite3.Connection, file_path: str) -> int:
    """
    מאתר מועמד לפי file_path; אם לא קיים - יוצר רשומה חדשה ומחזיר את ה-cv_id הרץ.
    """
    file_name = Path(file_path).name

    # קיים?
    cur = con.execute("SELECT cv_id FROM candidates WHERE file_path = ?", (file_path,))
    row = cur.fetchone()
    if row:
        # עדכון שם הקובץ אם השתנה
        con.execute("UPDATE candidates SET file_name=? WHERE cv_id=?", (file_name, row[0]))
        con.commit()
        return int(row[0])

    # יצירה
    cur = con.execute(
        "INSERT INTO candidates (file_path, file_name) VALUES (?, ?)",
        (file_path, file_name),
    )
    con.commit()
    return int(cur.lastrowid)

def upsert_age_score(
    con: sqlite3.Connection,
    cv_id: int,
    *,
    age_score: float | None,
    birth_year: int | None,
    age: int | None,
    reason: str,
    confidence: str,
    factor: float | None,
    final_score: float | None = None,   # הפרמטר נשאר בשביל תאימות לאחור
):
    """
    מעדכן/יוצר רשומת ציון גיל עבור cv_id נתון
    + מחשב final_score משוקלל כך ש-NULL נחשב כציון מלא.
    """

    # 1. מביאים את הסקורים הקיימים (אם יש)
    cur = con.execute(
        """
        SELECT
          age_score,
          distance_score,
          must_requirements_score,
          years_experience_score,
          nice_to_have_score
        FROM cv_scores
        WHERE cv_id = ?
        """,
        (cv_id,),
    )
    row = cur.fetchone()

    if row:
        # row יכול להיות tuple או sqlite3.Row – בשני המקרים אינדקסים עובדים
        existing_age, existing_dist, existing_must, existing_years, existing_nice = row
    else:
        existing_age = existing_dist = existing_must = existing_years = existing_nice = None

    # 2. קובעים את הערכים העדכניים לכל סעיף
    age_val   = age_score if age_score is not None else existing_age
    dist_val  = existing_dist
    must_val  = existing_must
    years_val = existing_years
    nice_val  = existing_nice

    # 3. NULL → ציון מלא
    def full_or(value, full):
        return full if value is None else value

    age_pts   = full_or(age_val,   10.0)
    dist_pts  = full_or(dist_val,  10.0)
    must_pts  = full_or(must_val,  40.0)
    years_pts = full_or(years_val, 20.0)
    nice_pts  = full_or(nice_val,  20.0)

    computed_final = age_pts + dist_pts + must_pts + years_pts + nice_pts

    # 4. שמירה בטבלה (שימי לב: final_score תמיד נקבע לערך שחישבנו)
    con.execute(
        """
        INSERT INTO cv_scores (
            cv_id, age_score, birth_year, age, age_reason,
            age_confidence, age_factor, final_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cv_id) DO UPDATE SET
            age_score       = excluded.age_score,
            birth_year      = excluded.birth_year,
            age             = excluded.age,
            age_reason      = excluded.age_reason,
            age_confidence  = excluded.age_confidence,
            age_factor      = excluded.age_factor,
            final_score     = excluded.final_score,
            updated_at      = (datetime('now','localtime'))
        """,
        (cv_id, age_score, birth_year, age, reason, confidence, factor, computed_final),
    )
    con.commit()


def link_cv_to_job(con: sqlite3.Connection, cv_id: int, job_id: int):
    """
    קושר CV למשרה (job_id מגיע מטבלת jobs ב-auth_server).
    אם הקישור כבר קיים – INSERT OR IGNORE מונע כפילות.
    """
    con.execute(
        """
        INSERT OR IGNORE INTO job_candidates (job_id, cv_id)
        VALUES (?, ?)
        """,
        (job_id, cv_id),
    )
    con.commit()
