import sqlite3
from tabulate import tabulate
from auth_server import init_db, DB_PATH  # ← מוסיפים שורה זו

def main():
    # קודם מוודאים שהטבלה users קיימת ושיש בה משתמשי דמו
    init_db()   # ← השורה החשובה

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id, email, role, password_hash FROM users")
    rows = cur.fetchall()

    headers = ["ID", "Email", "Role", "Password Hash"]
    print("\n=== Users in DB ===\n")
    print(tabulate(rows, headers=headers, tablefmt="pretty", stralign="right"))
    print("\nסה\"כ משתמשים:", len(rows))

    conn.close()

if __name__ == "__main__":
    main()
