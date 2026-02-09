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
  cv_id INTEGER NOT NULL,
  job_id INTEGER NOT NULL,

  age_score REAL,
  distance_score REAL,
  must_requirements_score REAL,
  years_experience_score REAL,
  nice_to_have_score REAL,
  final_score REAL,

  birth_year INTEGER,
  age INTEGER,
  age_reason TEXT,
  age_confidence TEXT,
  age_factor REAL,
  age_reason TEXT,

  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),

  PRIMARY KEY (cv_id, job_id),
  FOREIGN KEY(cv_id) REFERENCES candidates(cv_id)
);


"""

def connect(db_path: str) -> sqlite3.Connection:
    """פותח חיבור למסד הנתונים ויוצר טבלאות אם חסרות + מוסיף עמודות חסרות."""
    Path(os.path.dirname(db_path) or ".").mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path, timeout=30)

    # מומלץ כדי לצמצם נעילות
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("PRAGMA busy_timeout=5000;")  # 5 שניות המתנה אם DB נעול

    con.executescript(SCHEMA)

    # --- migration: add missing columns to existing cv_scores ---
    cols = {row[1] for row in con.execute("PRAGMA table_info(cv_scores)").fetchall()}

    missing = []
    if "age" not in cols:
        missing.append(("age", "INTEGER"))
    if "age_confidence" not in cols:
        missing.append(("age_confidence", "TEXT"))
    if "age_factor" not in cols:
        missing.append(("age_factor", "REAL"))

    for name, typ in missing:
        con.execute(f"ALTER TABLE cv_scores ADD COLUMN {name} {typ}")

    con.commit()
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
    job_id: int,
    cv_id: int,
    *,
    age_score: float | None,
    birth_year: int | None,
    age: int | None,
    reason: str,
    confidence: str,
    factor: float | None,
):
    con.execute(
        """
        INSERT INTO cv_scores (
            job_id, cv_id,
            age_score, birth_year, age, age_reason,
            age_confidence, age_factor
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, cv_id) DO UPDATE SET
            age_score       = excluded.age_score,
            birth_year      = excluded.birth_year,
            age             = excluded.age,
            age_reason      = excluded.age_reason,
            age_confidence  = excluded.age_confidence,
            age_factor      = excluded.age_factor,
            updated_at      = (datetime('now','localtime'))
        """,
        (job_id, cv_id, age_score, birth_year, age, reason, confidence, factor),
    )
    con.commit()

    recompute_final_score(con, job_id, cv_id)



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


def recompute_final_score(con: sqlite3.Connection, job_id: int, cv_id: int):
    con.execute(
        """
        UPDATE cv_scores
        SET final_score =
              COALESCE(age_score, 10)
            + COALESCE(distance_score, 10)
            + COALESCE(must_requirements_score, 0)
            + COALESCE(years_experience_score, 0)
            + COALESCE(nice_to_have_score, 0),
            updated_at = (datetime('now','localtime'))
        WHERE job_id = ? AND cv_id = ?
        """,
        (job_id, cv_id),
    )
    con.commit()
