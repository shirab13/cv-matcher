import re
from typing import Optional
from src.utils.dates import current_year, yy_to_yyyy

HEB_MONTHS = r'(?:ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר)'
ENG_MONTHS = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
WSP = r'[\s\u00A0\u200E\u200F]*'

BIRTH_LABEL = rf'(?:תאריך{WSP}לידה|ת\.?{WSP}לידה|תאריך{WSP}הולדת|DOB|Date{WSP}of{WSP}Birth|Birth(?:{WSP}Date)?|Birthdate|Born)'
DATE_CORE = (
    r'(?:'
    r'(?P<yyyy>\d{4})[./\-]\d{1,2}[./\-]\d{1,2}'
    r'|'
    r'\d{1,2}[./\-]\d{1,2}[./\-](?P<yyyy2>\d{4})'
    r'|'
    rf'{ENG_MONTHS}\s+\d{{1,2}},?\s+(?P<yyyy3>\d{{4}})'
    r'|'
    rf'\d{{1,2}}\s+{HEB_MONTHS}\s+(?P<yyyy4>\d{{4}})'
    r'|'
    r'\d{1,2}[./\-]\d{1,2}[./\-](?P<yy>\d{2})'
    r'|'
    rf'{ENG_MONTHS}\s+\d{{1,2}},?\s+(?P<yy2>\d{{2}})'
    r')'
)

PAT_BIRTH_INLINE = re.compile(rf'({BIRTH_LABEL}){WSP}[:：\-]?{WSP}({DATE_CORE})', re.IGNORECASE)
PAT_BORN_FREE   = re.compile(rf'(?:נולד(?:ה)?|Born)\s+(?:on{WSP})?({DATE_CORE})', re.IGNORECASE)

RANGE_SEP = r'[-–—~]'
PAT_YEAR   = re.compile(r'\b(19|20)\d{2}\b')
PAT_RANGE  = re.compile(rf'\b((?:19|20)\d{{2}})\s*{RANGE_SEP}\s*((?:19|20)\d{{2}})\b')

def _pick_year_from_date_match(m) -> Optional[int]:
    for name in ('yyyy', 'yyyy2', 'yyyy3', 'yyyy4', 'yy', 'yy2'):
        try:
            v = m.group(name)
            if v:
                return int(v) if len(v) == 4 else yy_to_yyyy(v)
        except IndexError:
            pass
    return None

def _reasonable_birth_year(y: int) -> bool:
    cy = current_year()
    return 1940 <= y <= cy - 10  # לא סביר מתחת לגיל 10

def infer_birth_year(text: str) -> Optional[int]:
    s = text or ""
    m = PAT_BIRTH_INLINE.search(s)
    if m:
        y = _pick_year_from_date_match(m)
        if y and _reasonable_birth_year(y):
            return y

    m2 = PAT_BORN_FREE.search(s)
    if m2:
        y = _pick_year_from_date_match(m2)
        if y and _reasonable_birth_year(y):
            return y

    years = []
    for rm in PAT_RANGE.finditer(s):
        try:
            start = int(rm.group(1))
            end   = int(rm.group(2))
            if start <= end:
                years.append(start)
        except ValueError:
            continue

    for ym in PAT_YEAR.finditer(s):
        try:
            years.append(int(ym.group(0)))
        except ValueError:
            pass

    if years:
        start_year = min(years)
        birth_guess = start_year - 18
        if _reasonable_birth_year(birth_guess):
            return birth_guess

    return None

def infer_age(text: str) -> Optional[int]:
    by = infer_birth_year(text)
    return None if by is None else (current_year() - by)
