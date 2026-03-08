import re
from datetime import datetime

CURRENT_YEAR = datetime.now().year

HE_MONTHS = (
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
)

PRESENT_WORDS = ("היום", "כיום", "עד היום", "נוכחי", "עכשיו")

DATE_RANGE_PATTERNS = [
    # 2020-2023 / 2020 – 2023 / 2020 עד 2023
    re.compile(r'(?P<start>20\d{2}|19\d{2})\s*(?:-|–|—|עד|to)\s*(?P<end>20\d{2}|19\d{2}|היום|כיום|עד היום)', re.IGNORECASE),
    re.compile(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*ש(?:נה|נים)\s*ניסיון'),
    # 01/2020 - 03/2022
    re.compile(r'(?P<start_m>\d{1,2})/(?P<start_y>20\d{2}|19\d{2})\s*(?:-|–|—|עד|to)\s*(?P<end_m>\d{1,2})/(?P<end_y>20\d{2}|19\d{2})', re.IGNORECASE),

    # 01/2020 - היום
    re.compile(r'(?P<start_m>\d{1,2})/(?P<start_y>20\d{2}|19\d{2})\s*(?:-|–|—|עד|to)\s*(?P<end_present>היום|כיום|עד היום)', re.IGNORECASE),
]

YEARS_REQ_PATTERNS = [
    re.compile(r'לפחות\s*(\d+(?:\.\d+)?)\s*ש(?:נה|נים)\s*ניסיון'),
    re.compile(r'ניסיון\s*של\s*(\d+(?:\.\d+)?)\s*ש(?:נה|נים)'),
    re.compile(r'(\d+(?:\.\d+)?)\+?\s*ש(?:נה|נים)\s*ניסיון'),
    re.compile(r'מעל\s*(\d+(?:\.\d+)?)\s*ש(?:נה|נים)\s*ניסיון'),
]

EXPERIENCE_SECTION_HEADERS = (
    "ניסיון תעסוקתי",
    "ניסיון מקצועי",
    "ניסיון",
    "תעסוקה",
    "רקע תעסוקתי",
    "היסטוריה תעסוקתית",
)

JOB_KEYWORDS_MAP = {
    "qa": [
        "qa", "בודק", "בודקת", "בדיקות", "בדיקות תוכנה",
        "בודק תוכנה", "בודקת תוכנה", "quality assurance",
        "בדיקות ידניות", "בדיקות אוטומציה", "automation", "manual"
    ],
    "backend": [
        "backend", "בקאנד", "שרת", "api", "node", "python", "php",
        "express", "fastify", "django", "flask", "laravel"
    ],
    "frontend": [
        "frontend", "פרונטאנד", "react", "vue", "angular",
        "javascript", "typescript", "css", "html"
    ],
    "fullstack": [
        "fullstack", "full stack", "פולסטאק", "react", "vue",
        "node", "python", "php", "api", "frontend", "backend"
    ],
    "devops": [
        "devops", "aws", "docker", "kubernetes", "ci/cd",
        "ansible", "terraform", "pulumi", "linux"
    ],
}

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("\u200f", " ").replace("\u200e", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_required_years_from_job_text(job_text: str) -> float | None:
    text = normalize_text(job_text)
    for pattern in YEARS_REQ_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                if len(m.groups()) >= 2:
                    return float(m.group(1))  # לוקחים את המינימום בטווח
                return float(m.group(1))
            except Exception:
                pass
    return None

def infer_target_keywords(job_text: str) -> list[str]:
    text = normalize_text(job_text)
    found = set()

    for group_keywords in JOB_KEYWORDS_MAP.values():
        for kw in group_keywords:
            if kw.lower() in text:
                found.add(kw.lower())

    # fallback: מילות מפתח בסיסיות מהטקסט עצמו
    if not found:
        words = re.findall(r"[א-תa-zA-Z+#/.]{2,}", text)
        stop = {
            "דרוש", "דרושה", "נדרש", "נדרשת", "משרה", "תפקיד", "עם", "של",
            "על", "ידע", "יכולת", "ניסיון", "לפחות", "יתרון", "חובה"
        }
        for w in words:
            if w not in stop and len(w) >= 3:
                found.add(w)

    return list(found)

def line_is_relevant(line: str, keywords: list[str]) -> bool:
    line_n = normalize_text(line)
    return any(kw in line_n for kw in keywords)

def years_between(start_year: int, end_year: int) -> float:
    if end_year < start_year:
        return 0.0
    return float(end_year - start_year)

def parse_year_range_from_line(line: str) -> float | None:
    line_n = normalize_text(line)

    for pattern in DATE_RANGE_PATTERNS:
        m = pattern.search(line_n)
        if not m:
            continue

        gd = m.groupdict()

        # 2020-2023
        if gd.get("start") and gd.get("end"):
            start_year = int(gd["start"])
            end_raw = gd["end"]
            end_year = CURRENT_YEAR if end_raw in PRESENT_WORDS else int(end_raw)
            return years_between(start_year, end_year)

        # 01/2020 - 03/2022
        if gd.get("start_y") and gd.get("end_y"):
            start_year = int(gd["start_y"])
            end_year = int(gd["end_y"])
            return years_between(start_year, end_year)

        # 01/2020 - היום
        if gd.get("start_y") and gd.get("end_present"):
            start_year = int(gd["start_y"])
            return years_between(start_year, CURRENT_YEAR)

    return None

def extract_relevant_experience_years(cv_text: str, job_text: str) -> float:
    lines = [line.strip() for line in cv_text.splitlines() if line.strip()]
    keywords = infer_target_keywords(job_text)

    total_years = 0.0
    used_ranges = []

    for i, line in enumerate(lines):
        years = parse_year_range_from_line(line)
        if years is None:
            continue

        # בודקים את השורה עצמה + שורה מעל + שורה מתחת
        context_lines = []
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(lines):
                context_lines.append(lines[j])

        context = " ".join(context_lines)

        if line_is_relevant(context, keywords):
            used_ranges.append((context, years))
            total_years += years

    # למנוע סכומים מוגזמים בגלל חפיפות/רעש
    return round(min(total_years, 50.0), 2)

def calculate_years_experience_score(candidate_years: float, required_years: float | None) -> float:
    MAX_SCORE = 30.0

    # אם לא הוגדרה דרישת ניסיון במשרה - לא מענישים
    if required_years is None or required_years <= 0:
        return MAX_SCORE

    if candidate_years <= 0:
        return 0.0

    ratio = min(candidate_years / required_years, 1.0)
    return round(ratio * MAX_SCORE, 2)
