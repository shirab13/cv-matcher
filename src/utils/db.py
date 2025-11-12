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
    final_score: float | None = None,
):
    """מעדכן/יוצר רשומת ציון גיל עבור cv_id נתון."""
    con.execute(
        """
        INSERT INTO cv_scores (
            cv_id, age_score, birth_year, age, age_reason,
            age_confidence, age_factor, final_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cv_id) DO UPDATE SET
            age_score=excluded.age_score,
            birth_year=excluded.birth_year,
            age=excluded.age,
            age_reason=excluded.age_reason,
            age_confidence=excluded.age_confidence,
            age_factor=excluded.age_factor,
            final_score=COALESCE(excluded.final_score, cv_scores.final_score),
            updated_at=(datetime('now','localtime'))
        """,
        (cv_id, age_score, birth_year, age, reason, confidence, factor, final_score),
    )
    con.commit()
