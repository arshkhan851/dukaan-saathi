import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = str(PROJECT_ROOT / "ledger.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL, -- 'credit' (udhaar given) or 'payment' (money received)
            note TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def log_transaction(customer_name: str, amount: float, transaction_type: str, note: str = ""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (customer_name, amount, transaction_type, note)
        VALUES (?, ?, ?, ?)
    ''', (customer_name, amount, transaction_type, note))
    conn.commit()
    conn.close()

def get_customer_balance(customer_name: str) -> float:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            SUM(CASE WHEN transaction_type = 'credit' THEN amount ELSE 0 END) -
            SUM(CASE WHEN transaction_type = 'payment' THEN amount ELSE 0 END)
        FROM transactions
        WHERE LOWER(customer_name) = LOWER(?)
    ''', (customer_name,))
    result = cursor.fetchone()[0]
    conn.close()
    return result if result is not None else 0.0

def get_daily_total(transaction_type: str) -> float:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT SUM(amount) FROM transactions 
        WHERE transaction_type = ? AND date(timestamp) = date('now', 'localtime')
    ''', (transaction_type,))
    result = cursor.fetchone()[0]
    conn.close()
    return result if result is not None else 0.0

if __name__ == "__main__":
    init_db()
