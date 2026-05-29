import pytest
import auth_server


@pytest.fixture
def app(tmp_path):
    """Flask app עם DB זמנית — לא נוגע בנתונים האמיתיים."""
    db_path = str(tmp_path / "test.db")
    auth_server.DB_PATH = db_path

    auth_server.init_db()

    auth_server.app.config["TESTING"] = True
    auth_server.app.config["SECRET_KEY"] = "test-secret-key"

    yield auth_server.app

    auth_server.DB_PATH = "cv_matcher.db"


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def hr_lead_client(client):
    """client מחובר כ-HR_LEAD (יכול ליצור משרות)."""
    client.post("/api/login", json={"email": "hr_lead@example.com", "password": "123456"})
    return client


@pytest.fixture
def recruiter_client(client):
    """client מחובר כ-RECRUITER."""
    client.post("/api/login", json={"email": "recruiter@example.com", "password": "123456"})
    return client
