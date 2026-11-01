import json
import sqlite3
import threading
from datetime import datetime, timezone
from .config import DB_PATH

LOCK = threading.RLock()

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def connection():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    return db

def init():
    with LOCK, connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL, content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, content TEXT NOT NULL,
            photo_filename TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, due_at TEXT,
            done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            notified_at TEXT
        );
        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL, request_text TEXT NOT NULL,
            analysis TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        ''')
        # Migration for existing TIKI SQLite databases: keep all older data.
        cols = {r['name'] for r in db.execute('PRAGMA table_info(reminders)').fetchall()}
        if 'notified_at' not in cols:
            db.execute('ALTER TABLE reminders ADD COLUMN notified_at TEXT')
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", ("mode", json.dumps("companion")))
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('active','false')")

def query(sql, params=()):
    with LOCK, connection() as db:
        return [dict(r) for r in db.execute(sql, params).fetchall()]

def execute(sql, params=()):
    with LOCK, connection() as db:
        cur = db.execute(sql, params)
        db.commit()
        return cur.lastrowid

def setting(key, default=None):
    rows = query('SELECT value FROM settings WHERE key=?', (key,))
    return json.loads(rows[0]['value']) if rows else default

def set_setting(key, value):
    execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))

def add_message(role, content):
    return execute('INSERT INTO messages(role, content, created_at) VALUES(?,?,?)', (role, content, now()))

def history(limit=32):
    return list(reversed(query('SELECT * FROM messages ORDER BY id DESC LIMIT ?', (limit,))))

def add_memory(content, source='user'):
    return execute('INSERT INTO memories(content,source,created_at) VALUES (?,?,?)', (content.strip(), source, now()))

def memories():
    return query('SELECT * FROM memories ORDER BY id DESC LIMIT 100')

def add_note(title, content, photo_filename=None):
    return execute('INSERT INTO notes(title,content,photo_filename,created_at) VALUES(?,?,?,?)', (title, content, photo_filename, now()))

def notes():
    return query('SELECT * FROM notes ORDER BY id DESC LIMIT 100')

def add_reminder(title, due_at=None):
    return execute('INSERT INTO reminders(title,due_at,created_at) VALUES(?,?,?)', (title, due_at, now()))

def reminders():
    return query('SELECT * FROM reminders ORDER BY done ASC, id DESC LIMIT 100')

def add_capture(filename, request_text, analysis):
    return execute('INSERT INTO captures(filename,request_text,analysis,created_at) VALUES(?,?,?,?)', (filename, request_text, analysis, now()))

def captures():
    return query('SELECT * FROM captures ORDER BY id DESC LIMIT 100')


def capture_by_id(capture_id: int):
    matches = query('SELECT * FROM captures WHERE id=?', (capture_id,))
    return matches[0] if matches else None


def remove_capture(capture_id: int):
    """Remove a photo's record and unlink its association from saved notes.

    Note text remains, so deleting an image does not destroy class notes.
    """
    with LOCK, connection() as db:
        row = db.execute('SELECT filename FROM captures WHERE id=?', (capture_id,)).fetchone()
        if not row:
            return None
        filename = row['filename']
        db.execute('UPDATE notes SET photo_filename=NULL WHERE photo_filename=?',(filename,))
        db.execute('DELETE FROM captures WHERE id=?',(capture_id,))
        db.commit()
    return filename

