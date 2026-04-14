# -*- coding: utf-8 -*-
"""Seed demo job postings (Hebrew) under every manager visible to users whose email contains 'bob'."""
import sqlite3

DB_PATH = "cv_matcher.db"

JOBS = [
    {
        "title": "ראש מדור הנהלת חשבונות וחשבות",
        "description": (
            "ניהול צוות עובדי הנהלת החשבונות, כולל פיקוח ובקרה על פעילות ותפוקות. "
            "הכנה, ניתוח וערכה של דוחות כספיים. "
            "אחריות על תפעול ובקרה של היבטי המיסוי בפעילות המכללה. "
            "עבודה שוטפת מול רשות המיסים הכוללת דיווחים, ביקורות ועדכונים. "
            "מעקב ודיווח על השקעות. קיום קשר שוטף עם הבנקים. "
            "ביצוע בדיקות ובקרות חשבונאיות. "
            "עיקר המשרה מקמפוס בבאר-שבע אך כוללת נסיעות לקמפוס אשדוד לפי הצורך."
        ),
        "must_requirements": (
            "תואר ראשון בכלכלה / חשבונאות\n"
            "רישיון בראיית חשבון - חובה\n"
            "ניסיון של 3 שנים בתפקיד דומה\n"
            "ידע ניסיון והיכרות עם מערכות ממוחשבות\n"
            "יכולת ביטוי גבוהה מאד בעל פה ובכתב\n"
            "שליטה בשפה האנגלית ברמה טובה מאוד\n"
            "יכולת עמידה בתנאי לחץ\n"
            "כושר ארגון יוזמה יסודיות אחריות\n"
            "תודעת שירות גבוהה ויחסי אנוש טובים"
        ),
        "nice_to_have": (
            "ניסיון קודם בעבודה במוסד להשכלה גבוהה או מלכר\n"
            "שליטה בתוכנת תפנית\n"
            "נכונות לעבודה בשעות לא שגרתיות על פי הצורך"
        ),
        "location": "באר שבע",
        "employment_type": "משרה מלאה",
        "work_mode": "פרונטלי",
        "required_years_experience": 3,
    },
    {
        "title": "אחראי/ת מבנים במחלקת תפעול",
        "description": (
            "אחריות על תחומי לוגיסטיקה, אחזקה, בינוי ומינהל משקי. "
            "אחריות על תפעול ותקינות המבנים בהיבטי ניקיון, גינון, סנטריה, פרזול ועוד. "
            "מתן מענה באירועי חירום ונהול חירום כללי. "
            "עבודה שוטפת מול גורמים רלוונטיים במכללה ומחוץ למכללה. "
            "עבודה במשמרות ובשעות נוספות כולל עבודה בימי שישי. "
            "ממונה - ראש מחלקת תפעול, קמפוס באר שבע."
        ),
        "must_requirements": (
            "12 שנות לימוד לפחות - חובה\n"
            "רישיון נהיגה - חובה\n"
            "שליטה בשפה העברית\n"
            "ניסיון בתחזוקת מבנים ובאחזקת מערכות חשמל ומיזוג אוויר, אינסטלציה, נגרות\n"
            "יכולת ארגון וביצוע מטלות ברמה גבוהה\n"
            "תודעת שירות גבוהה ויחסי אנוש מצוינים\n"
            "נכונות לעבודה מאומצת בשעות לא שגרתיות\n"
            "אחריות ומשמעת אישית גבוהה\n"
            "ניסיון עבודה בסביבה ממוחשבת"
        ),
        "nice_to_have": (
            "חשמלאי/ת בעל/ת רישיון מוסמך - יתרון\n"
            "הנדסאי/ת או טכנאי/ת חשמל או מיזוג אוויר בעל/ת רישיון מוסמך - יתרון"
        ),
        "location": "באר שבע",
        "employment_type": "משרה מלאה",
        "work_mode": "פרונטלי",
        "required_years_experience": 0,
    },
    {
        "title": "עוזר/ת מנהלי/ת - המחלקה להנדסה כימית",
        "description": (
            "ניהול אדמיניסטרטיבי ומתן שירות שוטף לראש המחלקה - "
            "כולל מענה טלפוני, טיפול בדואר, תיוק, הכנת דוחות, בניית מצגות, ניסוח תכתובות. "
            "ניהול יומן ולוח זמנים של ראש המחלקה. "
            "סיוע בתפעול השוטף של תכניות הלימודים. "
            "טיפול בפניות של סטודנטים. "
            "סיוע בניהול תקציב המחלקה. "
            "היקף - 50% משרה. קמפוס אשדוד."
        ),
        "must_requirements": (
            "תואר אקדמי - חובה\n"
            "שליטה מלאה ביישומי Office ואינטרנט - חובה\n"
            "ניסיון בעבודה אדמיניסטרטיבית\n"
            "כושר ארגון יוזמה יסודיות ואחריות\n"
            "יכולת עמידה במצבי לחץ ולוחות זמנים\n"
            "יכולת ניסוח בעל פה ובכתב ברמה גבוהה\n"
            "אנגלית ברמה גבוהה\n"
            "תודעת שירות גבוהה ויחסי אנוש מצוינים"
        ),
        "nice_to_have": "שליטה בתוכנת תפנית ובתוכנת מכולי - יתרון",
        "location": "אשדוד",
        "employment_type": "חצי משרה",
        "work_mode": "פרונטלי",
        "required_years_experience": 0,
    },
    {
        "title": "ספרן/ית",
        "description": (
            "מתן שירותי ייעוץ, השאלה והדרכה לסטודנטים בספרייה. "
            "קטלוג ספרים בעברית ובאנגלית. "
            "פיתוח מאגר הספרים, כתבי העת ומאגרי המידע של הספרייה. "
            "מתן מענה לצרכי הסטודנטים, המרצים וגורמים רלוונטיים נוספים. "
            "מעקב אחר שינויים טכנולוגיים הרלוונטיים לפעילות הספרייה. "
            "ממונה - מנהל/ת הספרייה. קמפוס באר שבע + קמפוס אשדוד."
        ),
        "must_requirements": (
            "השכלה אקדמית - חובה\n"
            "תואר שני בספרנות או מידענות - חובה\n"
            "היכרות עם מאגרי מידע הרלוונטיים לתחומי ההתמחות במכללה\n"
            "עברית ואנגלית ברמת שפת אם - דיבור קריאה ניסוח וכתיבה\n"
            "יכולת עבודה בסביבה ממוחשבת\n"
            "יכולת עבודה בצוות\n"
            "תודעת שירות גבוהה ויחסי אנוש טובים\n"
            "נכונות לעבודה בשעות לא שגרתיות על פי הצורך"
        ),
        "nice_to_have": "התמחות בתחומי ההנדסה - יתרון",
        "location": "באר שבע",
        "employment_type": "משרה מלאה",
        "work_mode": "פרונטלי",
        "required_years_experience": 0,
    },
    {
        "title": 'ממונה ביטחון / קב"ט המכללה',
        "description": (
            "ניהול, הכנה והפעלת מערך הביטחון והחירום. "
            "שמירה על המוכנות הביטחונית במצבי שגרה וחירום. "
            "ניהול סדרי הביטחון, האבטחה והחניה במכללה. "
            "תכנון, ארגון והפעלה של מערך האבטחה. "
            "ריכוז והכנת תוכניות מקלוט ומיגון. "
            "ביצוע ביקורות ובקרת שמירה ואבטחה. "
            "ניהול וביצוע הכשרות ותרגולות חירום. "
            "עבודה בשעות לא שגרתיות כולל שישי ושבת לפי הצורך. "
            "קמפוס באר שבע + קמפוס אשדוד."
        ),
        "must_requirements": (
            "בעל/ת תואר אקדמי ראשון\n"
            "בוגר/ת קורס קצינים בצהל או משטרה או שבס\n"
            "יוצא/ת יחידה קרבית\n"
            'בוגר/ת קורס מנהל אבטחה תו תקן משטרת ישראל\n'
            "בעל/ת ניסיון רב בעבודה בתחום הביטחון והאבטחה\n"
            "ניסיון בארגון אירועים רבי משתתפים ובכתיבת פקודות מבצע\n"
            "בעל/ת רקע בתחום מיגון אלקטרוני\n"
            "שליטה מלאה ביישומי המחשב וניסיון עבודה בסביבה ממוחשבת\n"
            "רישיון נהיגה בתוקף\n"
            "אישור הגדר רישום פלילי משטרת ישראל\n"
            "רישיון נשיאת נשק ומורשה לנשק אישי\n"
            "שליטה בשפה העברית"
        ),
        "nice_to_have": (
            "בוגר/ת קורס מנהל אירועים או קורס מוסדות חינוך "
            "או קורס מגישי עזרה ראשונה - יתרון"
        ),
        "location": "באר שבע",
        "employment_type": "משרה מלאה",
        "work_mode": "פרונטלי",
        "required_years_experience": 5,
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find all users whose email contains 'bob'
    cur.execute("SELECT id, email, role, manager_id FROM users WHERE email LIKE '%bob%'")
    bob_users = cur.fetchall()

    if not bob_users:
        print("No users with 'bob' in their email found.")
        conn.close()
        return

    # Determine the effective manager_id for each bob user:
    # - HR_LEAD sees jobs where jobs.manager_id = their own id
    # - everyone else sees jobs where jobs.manager_id = their users.manager_id
    manager_ids = set()
    for u in bob_users:
        if u["role"] == "HR_LEAD":
            manager_ids.add(u["id"])
        elif u["manager_id"]:
            manager_ids.add(u["manager_id"])
        print(f"  Found bob user: {u['email']} (role={u['role']})")

    if not manager_ids:
        print("Could not determine a manager_id for any bob user.")
        conn.close()
        return

    print(f"Seeding jobs under manager_id(s): {manager_ids}")

    total = 0
    for manager_id in manager_ids:
        for job in JOBS:
            cur.execute(
                """
                INSERT INTO jobs
                    (title, description, must_requirements, nice_to_have_requirements,
                     location, employment_type, work_mode, required_years_experience,
                     is_active, manager_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    job["title"], job["description"],
                    job["must_requirements"], job["nice_to_have"],
                    job["location"], job["employment_type"],
                    job["work_mode"], job["required_years_experience"],
                    manager_id,
                ),
            )
            print(f"  Inserted job id={cur.lastrowid}: {job['title']} (manager_id={manager_id})")
            total += 1

    conn.commit()
    conn.close()
    print(f"Done – {total} jobs added across {len(manager_ids)} manager(s).")


if __name__ == "__main__":
    main()
