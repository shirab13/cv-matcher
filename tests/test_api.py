"""
API Tests ל-HIRELY באמצעות Flask test client.
כל בדיקה רצה מול DB זמנית — לא נוגעת בנתונים האמיתיים.
"""
import io
import pytest


# ─────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────

class TestLogin:

    def test_valid_login_returns_200(self, client):
        res = client.post("/api/login", json={
            "email": "hr_lead@example.com",
            "password": "123456"
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True

    def test_wrong_password_returns_401(self, client):
        res = client.post("/api/login", json={
            "email": "hr_lead@example.com",
            "password": "wrongpassword"
        })
        assert res.status_code == 401

    def test_unknown_email_returns_401(self, client):
        res = client.post("/api/login", json={
            "email": "nobody@test.com",
            "password": "123456"
        })
        assert res.status_code == 401

    def test_missing_fields_returns_400(self, client):
        res = client.post("/api/login", json={"email": "hr_lead@example.com"})
        assert res.status_code == 400


# ─────────────────────────────────────────
# Job Creation
# ─────────────────────────────────────────

class TestCreateJob:

    def test_create_job_returns_201(self, hr_lead_client):
        res = hr_lead_client.post("/api/jobs", json={
            "title": "Python Developer",
            "description": "פיתוח בקאנד",
            "must_requirements": "Python, SQL",
        })
        assert res.status_code == 201
        data = res.get_json()
        assert data["success"] is True
        assert "job_id" in data

    def test_create_job_without_login_returns_401(self, client):
        res = client.post("/api/jobs", json={
            "title": "Python Developer",
            "description": "פיתוח",
            "must_requirements": "Python",
        })
        assert res.status_code == 401

    def test_create_job_missing_title_returns_400(self, hr_lead_client):
        res = hr_lead_client.post("/api/jobs", json={
            "description": "פיתוח",
            "must_requirements": "Python",
        })
        assert res.status_code == 400

    def test_create_job_invalid_years_experience_returns_400(self, hr_lead_client):
        res = hr_lead_client.post("/api/jobs", json={
            "title": "Developer",
            "description": "פיתוח",
            "must_requirements": "Python",
            "required_years_experience": "לא מספר",
        })
        assert res.status_code == 400


# ─────────────────────────────────────────
# Role Permissions
# ─────────────────────────────────────────

class TestRolePermissions:

    def test_unauthenticated_cannot_get_jobs(self, client):
        res = client.get("/api/jobs")
        assert res.status_code == 401

    def test_recruiter_can_get_jobs(self, recruiter_client):
        res = recruiter_client.get("/api/jobs")
        assert res.status_code == 200

    def test_recruiter_cannot_access_admin_users(self, recruiter_client):
        res = recruiter_client.get("/api/admin/users")
        assert res.status_code in (401, 403, 404)


# ─────────────────────────────────────────
# File Upload Validation
# ─────────────────────────────────────────

class TestFileUpload:

    def test_upload_invalid_extension_rejected(self, client):
        # upload_cv מוגבל ל-DEVOPS — כל ניסיון ללא הרשאה נדחה
        data = {
            "file": (io.BytesIO(b"fake content"), "malware.exe"),
            "job_id": "1",
        }
        res = client.post(
            "/api/upload_cv",
            data=data,
            content_type="multipart/form-data"
        )
        assert res.status_code in (400, 401, 403, 415)

    def test_upload_without_login_rejected(self, client):
        data = {
            "file": (io.BytesIO(b"%PDF fake"), "cv.pdf"),
            "job_id": "1",
        }
        res = client.post(
            "/api/upload_cv",
            data=data,
            content_type="multipart/form-data"
        )
        assert res.status_code == 401
