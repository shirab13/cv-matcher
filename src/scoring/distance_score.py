import re
import math
import json
from pathlib import Path
from typing import Optional

CITIES_JSON_PATH = Path(__file__).with_name("israel_cities.json")

with open(CITIES_JSON_PATH, "r", encoding="utf-8") as f:
    CITY_COORDS = json.load(f)

LOCATION_LABELS = [
    "מגורים",
    "מקום מגורים",
    "עיר",
    "כתובת",
    "אזור מגורים",
    "גר ב",
    "מתגורר ב",
    "מתגוררת ב"
]

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u200f", " ").replace("\u200e", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_candidate_city(cv_text: str) -> Optional[str]:
    text = normalize_text(cv_text)

    # קודם חיפוש לפי תוויות
    for city in CITY_COORDS.keys():
        for label in LOCATION_LABELS:
            pattern = rf"{label}\s*[:\-]?\s*{re.escape(city)}"
            if re.search(pattern, text):
                return city

    # אחר כך fallback: אם שם העיר פשוט מופיע בטקסט
    # נמיין לפי אורך כדי להעדיף "פתח תקווה" על "פתח"
    cities_sorted = sorted(CITY_COORDS.keys(), key=len, reverse=True)
    for city in cities_sorted:
        if city in text:
            return city

    return None

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c

def calculate_distance_km(candidate_city: str, job_city: str) -> Optional[float]:
    if candidate_city not in CITY_COORDS or job_city not in CITY_COORDS:
        return None

    lat1, lon1 = CITY_COORDS[candidate_city]
    lat2, lon2 = CITY_COORDS[job_city]
    return round(haversine_km(lat1, lon1, lat2, lon2), 2)

def calculate_distance_score(distance_km: Optional[float]) -> Optional[float]:
    # אם אין מקום מגורים מזוהה -> נשאיר NULL
    if distance_km is None:
        return None

    # עד 40 ק"מ - ניקוד מלא
    if distance_km <= 40:
        return 10.0

    # מעל 100 ק"מ - 0
    if distance_km >= 100:
        return 0.0

    # בין 40 ל-100 - ירידה ליניארית
    score = 10 * (100 - distance_km) / 60
    return round(score, 2)