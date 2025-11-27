import sqlite3
from tabulate import tabulate

DB_PATH = "users.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # שימי לב: password_hash ולא password
    cur.execute("SELECT id, email, role, password_hash FROM users")
    rows = cur.fetchall()

    headers = ["ID", "Email", "Role", "Password Hash"]
    print("\n=== Users in DB ===\n")
    print(tabulate(rows, headers=headers, tablefmt="pretty", stralign="right"))
    print("\nסה\"כ משתמשים:", len(rows))

    conn.close()

if __name__ == "__main__":
    main()
