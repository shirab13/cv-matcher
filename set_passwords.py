import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "users.db"

# כאן מגדירים איזה מייל איזו סיסמה יקבל
USERS = [
    ("hr_manager@example.com", "123456"),
    ("hr_lead@example.com", "123456"),
    ("recruiter@example.com", "123456"),
    ("devops@example.com", "123456"),
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for email, plain_password in USERS:
        hashed = generate_password_hash(plain_password)
        cur.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (hashed, email),
        )
        print(f"עודכן: {email}")

    conn.commit()
    conn.close()
    print("✅ סיסמאות עודכנו בהצלחה")

if __name__ == "__main__":
    main()
