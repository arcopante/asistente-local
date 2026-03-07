"""
database.py — Gestión de historial de conversación en SQLite
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, List
from pathlib import Path


DB_PATH = Path(__file__).parent / "history.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa la base de datos y crea las tablas necesarias."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                model       TEXT,
                label       TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                tokens      INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL,
                total_tokens    INTEGER DEFAULT 0,
                total_messages  INTEGER DEFAULT 0,
                model           TEXT,
                updated_at      TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
        """)


def new_session(model: Optional[str] = None, label: Optional[str] = None) -> int:
    """Crea una nueva sesión y devuelve su ID."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (created_at, model, label) VALUES (?, ?, ?)",
            (datetime.now().isoformat(), model, label)
        )
        session_id = cur.lastrowid
        conn.execute(
            "INSERT INTO stats (session_id, updated_at) VALUES (?, ?)",
            (session_id, datetime.now().isoformat())
        )
        return session_id


def save_message(session_id: int, role: str, content: str, tokens: int = 0):
    """Guarda un mensaje en el historial."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp, tokens) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, datetime.now().isoformat(), tokens)
        )
        conn.execute("""
            UPDATE stats
            SET total_tokens = total_tokens + ?,
                total_messages = total_messages + 1,
                updated_at = ?
            WHERE session_id = ?
        """, (tokens, datetime.now().isoformat(), session_id))


def get_history(session_id: int, limit: int = 50) -> List[dict]:
    """Recupera el historial de mensajes de una sesión."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_stats(session_id: int) -> dict:
    """Devuelve estadísticas de la sesión actual."""
    with get_connection() as conn:
        stats = conn.execute(
            "SELECT * FROM stats WHERE session_id = ?", (session_id,)
        ).fetchone()
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        total_sessions = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
    return {
        "session_id": session_id,
        "created_at": session["created_at"] if session else "-",
        "model": session["model"] if session else "-",
        "total_tokens": stats["total_tokens"] if stats else 0,
        "total_messages": stats["total_messages"] if stats else 0,
        "total_sessions_ever": total_sessions,
    }


def update_session_model(session_id: int, model: str):
    with get_connection() as conn:
        conn.execute("UPDATE sessions SET model = ? WHERE id = ?", (model, session_id))
        conn.execute("UPDATE stats SET model = ? WHERE session_id = ?", (model, session_id))


def list_sessions(limit: int = 10) -> List[dict]:
    """Lista las últimas sesiones."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT s.id, s.created_at, s.model, st.total_messages FROM sessions s "
            "LEFT JOIN stats st ON s.id = st.session_id ORDER BY s.id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def search_messages(query: str, limit: int = 20) -> List[dict]:
    """Busca mensajes en todo el historial que contengan el texto dado."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.role, m.content, m.timestamp, s.model, s.id as session_id
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            WHERE m.content LIKE ?
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (f"%{query}%", limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_summary(session_id: int) -> Optional[str]:
    """Devuelve el resumen guardado de una sesión, si existe."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT label FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row and row["label"] and row["label"].startswith("summary:"):
        return row["label"][8:]
    return None


def save_session_summary(session_id: int, summary: str):
    """Guarda un resumen compacto de la sesión en el campo label."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET label = ? WHERE id = ?",
            (f"summary:{summary}", session_id)
        )


def delete_session(session_id: int) -> bool:
    """Borra una sesion y todos sus mensajes y stats."""
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not rows:
            return False
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM stats WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return True


def delete_all_sessions_except(keep_session_id: int) -> int:
    """Borra todas las sesiones excepto la indicada. Devuelve el numero de sesiones borradas."""
    with get_connection() as conn:
        ids = conn.execute(
            "SELECT id FROM sessions WHERE id != ?", (keep_session_id,)
        ).fetchall()
        count = len(ids)
        for row in ids:
            sid = row["id"]
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM stats WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    return count
