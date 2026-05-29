"""
Edge Case Tests — בודק שהמערכת לא קורסת על קלטים קיצוניים.
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


class TestNullAndEmptyInputs:

    def test_distance_score_none(self):
        assert calculate_distance_score(None) is None

    def test_distance_km_unknown_city(self):
        assert calculate_distance_km("עיר לא קיימת", "תל אביב") is None

    def test_distance_km_both_unknown(self):
        assert calculate_distance_km("???", "!!!") is None

    def test_city_extraction_empty_string(self):
        assert extract_candidate_city("") is None

    def test_city_extraction_numbers_only(self):
        assert extract_candidate_city("12345 6789") is None

    def test_extract_skills_empty(self):
        assert extract_skills("") is None

    def test_extract_skills_none(self):
        assert extract_skills(None) is None

    def test_extract_skills_no_keywords(self):
        assert extract_skills("עובד קשה עם ניסיון רב בתחום") is None

    def test_age_penalty_none_age(self):
        score, detail = apply_age_penalty(80.0, None)
        assert score == 80.0

    def test_experience_score_none_requirement(self):
        assert calculate_years_experience_score(2, None) == 30.0

    def test_experience_score_zero_requirement(self):
        assert calculate_years_experience_score(2, 0) == 30.0


class TestExtremeValues:

    def test_distance_score_very_large(self):
        assert calculate_distance_score(9999) == 0.0

    def test_distance_score_negative(self):
        # מרחק שלילי אמור לקבל ניקוד מלא (קרוב)
        assert calculate_distance_score(-5) == 10.0

    def test_experience_score_way_over_requirement(self):
        # 20 שנות ניסיון כשדרוש 2 — לא יעלה מעל MAX
        assert calculate_years_experience_score(20, 2) == 30.0

    def test_age_penalty_very_old(self):
        score, detail = apply_age_penalty(100.0, 90)
        assert score == pytest.approx(90.0)
        assert detail["penalized"] is True


class TestApiEdgeCases:

    def test_login_empty_body_returns_400(self, client):
        res = client.post("/api/login", json={})
        assert res.status_code == 400

    def test_login_no_json_returns_400(self, client):
        res = client.post("/api/login", data="not json", content_type="text/plain")
        assert res.status_code in (400, 415)

    def test_get_nonexistent_job_returns_error(self, hr_lead_client):
        res = hr_lead_client.get("/api/jobs/99999")
        assert res.status_code in (403, 404)

    def test_get_nonexistent_candidate_cv(self, hr_lead_client):
        res = hr_lead_client.get("/api/candidates/99999/cv-file-pdf")
        assert res.status_code == 404
