"""
database.py
Handle penyimpanan memory percakapan per-user pakai SQLite.
Unlimited history disimpan per user_id, di-load pas bot mau reply.
"""

import sqlite3
# --- PERUBAHAN DI SINI: Tambahkan timezone ---
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = "bot_memory.db"


def init_db():
    """Bikin tabel kalau belum ada. Panggil sekali pas bot start."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,          -- 'user' atau 'assistant'
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id ON conversations(user_id)
        """)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def save_message(user_id: str, role: str, content: str):
    """Simpan satu pesan (dari user atau bot) ke history."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            # --- PERUBAHAN DI SINI: Ganti utcnow() menjadi now(timezone.utc) ---
            (str(user_id), role, content, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()


def get_history(user_id: str, limit: int = 30):
    """
    Ambil history percakapan user, urut dari paling lama ke paling baru.
    limit=30 artinya ambil 30 pesan TERAKHIR (bukan menghapus data lama di DB,
    cuma dibatasi supaya prompt ke Gemini gak kepanjangan / boros token).
    """
    with get_conn() as conn:
        cursor = conn.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (str(user_id), limit)
        )
        rows = cursor.fetchall()
    rows.reverse()  # balik jadi urutan kronologis
    return [{"role": role, "content": content} for role, content in rows]


def clear_history(user_id: str):
    """Optional: buat command reset memory user tertentu."""
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (str(user_id),))
        conn.commit()