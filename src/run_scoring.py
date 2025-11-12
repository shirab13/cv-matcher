from __future__ import annotations
import argparse, json, re
from datetime import datetime
from pathlib import Path

# חילוץ טקסט מכל סוג קובץ
from src.text_extractors.universal import extract_text_any
# חיבור למסד נתונים
from src.utils import db as dbutil

CURRENT_YEAR = datetime.now().year

# ---------- זיהוי שנה/גיל ----------
PAT_BIRTH_PHRASES = re.compile(
    r"""(?ix)
    (?:ת[.\s]*לידה|תאריך\s*לידה|שנת\s*לידה|יליד(?:ה)?|DOB|born(?:\s*in)?)
    [^\d]{0,12}
    (?:
        (?P<dd>\d{1,2})[./\-](?P<mm>\d{1,2})[./\-](?P<yyyy>\d{4})
        |
        (?P<yyyy2>19\d{2}|20\d{2})
    )
    """,
    re.UNICODE
)

# טווח שנים (למשל שירות/ניסיון): "2014-2017", "2019–2021"
PAT_RANGE = re.compile(r"(19\d{2}|20\d{2})\s*[-–]\s*(19\d{2}|20\d{2})")


def infer_birth_year_simple(text: str) -> tuple[int|None, str]:
    s = text or ""
    m = PAT_BIRTH_PHRASES.search(s)
    if m:
        if m.group("yyyy"):
            return int(m.group("yyyy")), "explicit_date"
        if m.group("yyyy2"):
            return int(m.group("yyyy2")), "explicit_year"

    rm = PAT_RANGE.search(s)
    if rm:
        y1, y2 = int(rm.group(1)), int(rm.group(2))
        # קטנה מבין השנים פחות 18 → הערכת שנת לידה
        return min(y1, y2) - 18, "range_minus_18"

    return None, "none"


def age_from_birth_year(by: int|None) -> int|None:
    if by is None:
        return None
    return max(0, CURRENT_YEAR - by)


def apply_age_penalty(base_score: float, age: int|None) -> dict:
    """
    אם age>50 → הורדה של 10%.
    מחזיר dict עם factor ו-score_final.
    """
    if age is None:
        return {"penalized": False, "factor": 1.0, "score_final": base_score}
    if age > 50:
        final = round(base_score * 0.9, 2)
        return {"penalized": True, "factor": 0.9, "score_final": final}
    return {"penalized": False, "factor": 1.0, "score_final": base_score}


def collect_targets(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        files = []
        for suf in (".txt", ".docx", ".pdf"):
            files.extend(path.rglob(f"*{suf}"))
        return sorted(files)
    return []


def main():
    ap = argparse.ArgumentParser(description="Age scoring with DB storage")
    ap.add_argument("input_path", help="קובץ יחיד או תיקייה (txt/docx/pdf)")
    ap.add_argument("--base", type=float, default=100.0, help="Base score (ברירת מחדל 100)")
    ap.add_argument("--debug", action="store_true", help="מציג מידע דיבאג")
    ap.add_argument("--db", type=str, default="cv_matcher.db", help="נתיב לקובץ SQLite (ברירת מחדל cv_matcher.db)")
    args = ap.parse_args()

    # חיבור למסד נתונים (אם לא קיים – נוצר אוטומטית)
    con = dbutil.connect(args.db)

    root = Path(args.input_path)
    items = collect_targets(root)
    if args.debug:
        print(f"[DEBUG] scanning: {root} | found {len(items)} file(s)")

    if not items:
        print("No supported files found (txt/docx/pdf).")
        return

    for p in items:
        print(f"==> {p}")
        text = extract_text_any(str(p)) or ""
        if args.debug:
            print(f"[DEBUG] text length: {len(text)} chars")
            if len(text) > 0:
                print(f"[DEBUG] preview: {text[:200].replace('\\n',' ')}")

        by, reason = infer_birth_year_simple(text)
        age = age_from_birth_year(by)
        penalty = apply_age_penalty(args.base, age)

        print(f"   Birth year (inferred): {by}   (reason={reason})")
        print(f"   Age (inferred):        {age}")
        print(f"   Penalized:             {penalty['penalized']} (factor={penalty['factor']})")
        print(f"   Score:                 {args.base:.2f} -> {penalty['score_final']:.2f}")

        # 🔹 שמירה למסד הנתונים
        cv_id = dbutil.upsert_candidate(con, str(p))
        dbutil.upsert_age_score(
            con, cv_id,
            age_score=penalty["score_final"],
            birth_year=by,
            age=age,
            reason=reason,
            confidence="N/A",
            factor=penalty["factor"],
            final_score=None
        )

        # בנוסף נשמור גם קובץ JSON כמו קודם
        out = {
            "file": str(p),
            "birth_year": by,
            "age": age,
            "age_penalty": {
                "penalized": penalty["penalized"],
                "factor": penalty["factor"],
            },
            "final_score": penalty["score_final"],
            "reason": reason,
            "year_now": CURRENT_YEAR,
        }
        out_path = p.with_suffix(p.suffix + ".age_scoring.json")
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"   Saved: {out_path}\n")


if __name__ == "__main__":
    main()
