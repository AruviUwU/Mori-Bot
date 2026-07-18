"""
database.py
Handle penyimpanan memory percakapan per-user pakai SQLite.
Unlimited history disimpan per user_id, di-load pas bot mau reply.
"""

import json
import sqlite3
from datetime import datetime
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
                attachments TEXT,            -- JSON array [{url, mime_type, filename}, ...] atau NULL
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id ON conversations(user_id)
        """)

        # Migrasi buat DB lama yang dibuat sebelum kolom attachments ada
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(conversations)")]
        if "attachments" not in existing_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN attachments TEXT")

        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def save_message(user_id: str, role: str, content: str, attachments: list[dict] | None = None):
    """
    Simpan satu pesan (dari user atau bot) ke history.

    attachments: optional list of dict, misal
        [{"url": "...", "mime_type": "image/png", "filename": "foto.png"}]
    Disimpan sebagai JSON string di kolom attachments (NULL kalau gak ada).
    """
    attachments_json = json.dumps(attachments) if attachments else None
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, attachments, timestamp) VALUES (?, ?, ?, ?, ?)",
            (str(user_id), role, content, attachments_json, datetime.utcnow().isoformat())
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
            "SELECT role, content, attachments FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (str(user_id), limit)
        )
        rows = cursor.fetchall()
    rows.reverse()  # balik jadi urutan kronologis
    result = []
    for role, content, attachments_json in rows:
        attachments = json.loads(attachments_json) if attachments_json else None
        result.append({"role": role, "content": content, "attachments": attachments})
    return result


def clear_history(user_id: str):
    """Optional: buat command reset memory user tertentu."""
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (str(user_id),))
        conn.commit()