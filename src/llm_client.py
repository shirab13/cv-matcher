"""
LLM-based CV analysis using Groq (free tier).
Extracts structured data from an anonymized CV relative to a job posting,
then calculates a score using the same weights as the existing algorithm.
"""

import json
import os
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.environ["GROQ_API_KEY"]
_MODEL   = "llama-3.3-70b-versatile"
_URL     = "https://api.groq.com/openai/v1/chat/completions"

# Same weights as the existing scoring system (db.py: recompute_final_score)
MUST_WEIGHT       = 40.0
EXPERIENCE_WEIGHT = 30.0
NICE_WEIGHT       = 10.0
DISTANCE_WEIGHT   = 10.0
AGE_WEIGHT        = 10.0

SYSTEM_PROMPT = """אתה מנתח קורות חיים מקצועי. קרא את קורות החיים ואת דרישות המשרה המצורפות,
ואז החזר אך ורק JSON תקין (ללא markdown, ללא טקסט נוסף) עם המבנה הבא:

{
  "years_of_experience": <מספר שנות ניסיון רלוונטי כמספר שלם, או null>,
  "mandatory_met": <מספר דרישות חובה שהמועמד עומד בהן>,
  "mandatory_total": <סך הדרישות חובה>,
  "bonus_met": <מספר דרישות יתרון שהמועמד עומד בהן>,
  "bonus_total": <סך דרישות היתרון, 0 אם אין>,
  "estimated_age": <גיל משוער כמספר, או null>,
  "candidate_city": <עיר מגורים בעברית, או null>,
  "education": <מחרוזת של עד 5 מילים בדיוק: תואר + תחום בלבד. דוגמה: "תואר ראשון בהנדסת תוכנה". ללא מוסד, ללא שנים, ללא כל דבר נוסף. null אם לא ברור>,
  "skills": [<בין 3 ל-6 כלים/טכנולוגיות ספציפיות בלבד. לא מיומנויות רכות. לדוגמה: ["Excel", "Python", "SAP"]>],
  "professional_summary": <בדיוק 2 משפטים קצרים בעברית. משפט 1: תחום עבודה + שנות ניסיון כוללות. משפט 2: תפקיד אחרון בלבד. אסור להעתיק מהטקסט. מקסימום 30 מילה סה"כ>
}

כללים:
- ספור כל דרישת חובה בנפרד (כל שורה/בולט = דרישה אחת)
- דרישה נחשבת "מכוסה" אם המועמד מציג ניסיון או ידע רלוונטי ברמה של 50% ומעלה
- אם אין דרישות יתרון במשרה, החזר bonus_total: 0 ו-bonus_met: 0
- החזר JSON בלבד, ללא שום טקסט נוסף"""


def extract_cv_data(cv_text: str, must_requirements: str, nice_requirements: str = "", few_shot_context: str = "") -> dict:
    """
    Send anonymized CV + job requirements to Groq.
    Returns structured extraction dict, or None on failure.
    """
    user_message = f"""קורות חיים:
{cv_text}

דרישות חובה:
{must_requirements or 'לא צוינו'}

דרישות יתרון:
{nice_requirements or 'לא צוינו'}"""

    if few_shot_context:
        user_message += f"\n\nתיקוני מגייסים מהעבר (לכיול הציון):\n{few_shot_context}"

    try:
        payload = json.dumps({
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        req = urllib.request.Request(
            _URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {_API_KEY}",
                "Content-Type":  "application/json",
                "User-Agent":    "python-requests/2.31.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        raw = result["choices"][0]["message"]["content"].strip()
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        print(f"[llm_client] Groq HTTP {e.code}: {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"[llm_client] Groq error: {e}")
        return None


def calculate_llm_score(extracted: dict, required_years: float | None = None,
                        job_city: str | None = None) -> dict:
    """
    Apply the same scoring weights as the existing algorithm to LLM-extracted data.
    Returns a dict with individual scores and llm_final_score (0-100).
    """
    if extracted is None:
        return None

    # --- Must requirements (0-40) ---
    m_total = extracted.get("mandatory_total") or 0
    m_met   = extracted.get("mandatory_met") or 0
    must_score = round(MUST_WEIGHT * (m_met / m_total), 2) if m_total > 0 else 0.0

    # --- Years of experience (0-30) ---
    candidate_years = extracted.get("years_of_experience")
    if candidate_years is None or candidate_years <= 0:
        exp_score = 0.0
    elif required_years is None or required_years <= 0:
        exp_score = EXPERIENCE_WEIGHT
    else:
        ratio = min(candidate_years / required_years, 1.0)
        exp_score = round(ratio * EXPERIENCE_WEIGHT, 2)

    # --- Nice to have (0-10) ---
    n_total = extracted.get("bonus_total") or 0
    n_met   = extracted.get("bonus_met") or 0
    if n_total == 0:
        nice_score = NICE_WEIGHT  # no bonus requirements → full points
    else:
        nice_score = round(NICE_WEIGHT * (n_met / n_total), 2)

    # --- Age (0-10) ---
    age = extracted.get("estimated_age")
    age_score = AGE_WEIGHT if (age is None or age <= 50) else 0.0

    # --- Distance (0-10) ---
    distance_score = None
    candidate_city = extracted.get("candidate_city")
    if candidate_city and job_city:
        try:
            from src.scoring.distance_score import calculate_distance_km, calculate_distance_score
            km = calculate_distance_km(candidate_city, job_city)
            distance_score = calculate_distance_score(km)
        except Exception:
            pass

    distance_score_final = distance_score if distance_score is not None else DISTANCE_WEIGHT

    llm_final_score = round(
        must_score + exp_score + nice_score + age_score + distance_score_final, 2
    )

    return {
        "llm_must_score":     must_score,
        "llm_exp_score":      exp_score,
        "llm_nice_score":     nice_score,
        "llm_age_score":      age_score,
        "llm_distance_score": distance_score_final,
        "llm_final_score":    llm_final_score,
        "llm_extracted":      extracted,
    }
