# auth_server.py
import os
import sqlite3
from flask import (
    Flask,
    request,
    jsonify,
    session,
    redirect,
    render_template,
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = "cv_matcher.db"

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"   # להחליף בסוד אמיתי בפרודקשן
CORS(app)


# ----------------- ROUTES בסיס -----------------

@app.route("/")
def index():
    # דף ההתחברות – templates/login.html
    return render_template("login.html")


# ----------------- דשבורדים לפי תפקיד -----------------

@app.route("/dashboard/hr-manager")
def hr_manager_dashboard():
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "HR_MANAGER":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל/ת HR"
    return render_template("hr_manager_dashboard.html", user_email=user_email)


@app.route("/dashboard/recruitment-manager")
def rm_dashboard():
    # אם תרצי, אפשר להוסיף כאן בדיקת תפקיד HR_LEAD
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "HR_LEAD":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל/ת גיוס"
    return render_template("recruitment_manager_dashboard.html", user_email=user_email)


@app.route("/dashboard/recruiter")
def recruiter_dashboard():
    if "user_id" not in session:
        return redirect("/")

    if session.get("role") != "RECRUITER":
        return "אין לך הרשאה לדף הזה", 403

    user_name = session.get("email") or "מגייס/ת"
    return render_template("recruiter_dashboard.html", user_name=user_name)


@app.route("/dashboard/devops")
def devops_dashboard():
    # בדיקת התחברות
    if "user_id" not in session:
        return redirect("/")

    # בדיקת תפקיד
    if session.get("role") != "DEVOPS":
        return "אין לך הרשאה לדף הזה", 403

    user_email = session.get("email") or "מנהל מערכת"
    # נשים את השם בדף
    return render_template("devops_dashboard.html", user_email=user_email)

# ----------------- LOGOUT -----------------

@app.route("/logout")
def logout():
    """
    התנתקות – מנקה את ה-session ומחזיר לדף ההתחברות
    """
    session.clear()
    return redirect("/")


# ----------------- DB פונקציות -----------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """יוצר טבלת משתמשים ומוסיף 4 משתמשי דמו אם עדיין לא קיימים."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        )
        """
    )

    # 4 משתמשי דמו
    demo_users = [
        ("hr_manager@example.com", "123456", "HR_MANAGER"),
        ("hr_lead@example.com", "123456", "HR_LEAD"),
        ("recruiter@example.com", "123456", "RECRUITER"),
        ("devops@example.com", "123456", "DEVOPS"),
    ]

    for email, plain_pwd, role in demo_users:
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone() is None:
            pwd_hash = generate_password_hash(plain_pwd)
            cur.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
                (email, pwd_hash, role),
            )

    conn.commit()
    conn.close()
    print("✅ DB Ready – users.db נוצר (אם לא היה) ונטענו 4 משתמשי דמו.")


# ----------------- LOGIN API -----------------

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON body"}), 400

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"success": False, "message": "חסר אימייל או סיסמה"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return jsonify({"success": False, "message": "משתמש לא נמצא"}), 401

    if not check_password_hash(row["password_hash"], password):
        return jsonify({"success": False, "message": "סיסמה שגויה"}), 401

    # שומרים בסשן
    session["user_id"] = row["id"]
    session["email"] = row["email"]
    session["role"] = row["role"]

    role = row["role"]

    redirect_map = {
        "HR_MANAGER": "/dashboard/hr-manager",
        "HR_LEAD": "/dashboard/recruitment-manager",
        "RECRUITER": "/dashboard/recruiter",
        "DEVOPS": "/dashboard/devops",
    }

    return jsonify(
        {
            "success": True,
            "message": "התחברת בהצלחה",
            "role": role,
            "redirect_url": redirect_map.get(role, "/"),
        }
    )


# ----------------- MAIN -----------------

if __name__ == "__main__":
    init_db()

    print("📂 משתמש בקובץ DB:", DB_PATH)
    app.run(host="127.0.0.1", port=5000, debug=True)
