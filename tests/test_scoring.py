"""
Unit tests לפונקציות הניקוד של HIRELY.
כל בדיקה עצמאית — לא דורשת DB או שרת.
"""
import pytest
from src.scoring.distance_score import (
    calculate_distance_score,
    calculate_distance_km,
    extract_candidate_city,
)
from src.scoring.age_score import apply_age_penalty
from src.scoring.experience_score import calculate_years_experience_score
from auth_server import extract_skills


# ─────────────────────────────────────────
# Distance Score
# ─────────────────────────────────────────

class TestDistanceScore:

    def test_same_city_gets_full_score(self):
        assert calculate_distance_score(0) == 10.0

    def test_under_40km_gets_full_score(self):
        assert calculate_distance_score(30) == 10.0

    def test_over_100km_gets_zero(self):
        assert calculate_distance_score(150) == 0.0

    def test_exactly_100km_gets_zero(self):
        assert calculate_distance_score(100) == 0.0

    def test_midrange_70km_is_partial(self):
        score = calculate_distance_score(70)
        assert 0 < score < 10

    def test_none_distance_returns_none(self):
        assert calculate_distance_score(None) is None


class TestDistanceKm:

    def test_same_city_is_zero(self):
        km = calculate_distance_km("תל אביב", "תל אביב")
        assert km == 0.0

    def test_known_cities_return_positive_distance(self):
        km = calculate_distance_km("תל אביב", "חיפה")
        assert km is not None
        assert km > 0

    def test_unknown_city_returns_none(self):
        assert calculate_distance_km("עיר לא קיימת", "תל אביב") is None


class TestExtractCity:

    def test_city_with_label(self):
        assert extract_candidate_city("מגורים: תל אביב") == "תל אביב"

    def test_city_in_free_text(self):
        assert extract_candidate_city("גר בחיפה ועובד בצפון") == "חיפה"

    def test_no_city_returns_none(self):
        assert extract_candidate_city("אין כאן שם עיר") is None

    def test_empty_text_returns_none(self):
        assert extract_candidate_city("") is None


# ─────────────────────────────────────────
# Age Score
# ─────────────────────────────────────────

class TestAgePenalty:

    def test_age_over_50_gets_penalty(self):
        score, detail = apply_age_penalty(100.0, 55)
        assert score == pytest.approx(90.0)
        assert detail["penalized"] is True

    def test_age_under_50_no_penalty(self):
        score, detail = apply_age_penalty(100.0, 35)
        assert score == 100.0
        assert detail["penalized"] is False

    def test_no_age_no_penalty(self):
        score, detail = apply_age_penalty(100.0, None)
        assert score == 100.0
        assert detail["penalized"] is False

    def test_age_exactly_50_no_penalty(self):
        score, detail = apply_age_penalty(100.0, 50)
        assert score == 100.0


# ─────────────────────────────────────────
# Experience Score
# ─────────────────────────────────────────

class TestExperienceScore:

    def test_meets_requirement_gets_full(self):
        assert calculate_years_experience_score(5, 3) == 30.0

    def test_exact_match_gets_full(self):
        assert calculate_years_experience_score(3, 3) == 30.0

    def test_no_experience_gets_zero(self):
        assert calculate_years_experience_score(0, 3) == 0.0

    def test_no_requirement_gets_full(self):
        assert calculate_years_experience_score(0, None) == 30.0

    def test_partial_experience_is_proportional(self):
        score = calculate_years_experience_score(1, 3)
        assert score == pytest.approx(10.0)


# ─────────────────────────────────────────
# Extract Skills
# ─────────────────────────────────────────

class TestExtractSkills:

    def test_finds_python_and_sql(self):
        result = extract_skills("Experienced developer with Python and SQL")
        assert "python" in result
        assert "sql" in result

    def test_finds_excel(self):
        result = extract_skills("Proficient in Excel and PowerPoint")
        assert "excel" in result

    def test_case_insensitive(self):
        result = extract_skills("REACT developer with NODE.JS")
        assert "react" in result

    def test_no_skills_returns_none(self):
        assert extract_skills("עובד מסור עם ניסיון רב") is None

    def test_empty_text_returns_none(self):
        assert extract_skills("") is None
