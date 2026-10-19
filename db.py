import hashlib
import os
import secrets
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "freefriends.db")
GROUP_ID_BYTES = 8
CODE_BYTES = 16

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    admin_hash TEXT
);
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT,
    ics_text TEXT,
    code_hash TEXT NOT NULL UNIQUE
);
"""


def query(sql, args=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, args).fetchall()
        conn.commit()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # older databases were created before groups had an admin code
    columns = [row[1] for row in conn.execute("PRAGMA table_info(groups)")]
    if "admin_hash" not in columns:
        conn.execute("ALTER TABLE groups ADD COLUMN admin_hash TEXT")
        conn.commit()
    conn.close()


def hash_code(code):
    return hashlib.sha256(code.encode()).hexdigest()


def create_group(name):
    group_id = secrets.token_urlsafe(GROUP_ID_BYTES)
    admin_code = secrets.token_urlsafe(CODE_BYTES)
    sql = "INSERT INTO groups (id, name, admin_hash) VALUES (?, ?, ?)"
    query(sql, (group_id, name, hash_code(admin_code)))
    return group_id, admin_code


def get_group(group_id):
    rows = query("SELECT * FROM groups WHERE id = ?", (group_id,))
    return rows[0] if rows else None


def count_people(group_id):
    sql = "SELECT COUNT(*) AS n FROM people WHERE group_id = ?"
    return query(sql, (group_id,))[0]["n"]


def list_people(group_id):
    sql = "SELECT id, name, url, ics_text FROM people WHERE group_id = ? ORDER BY id"
    return query(sql, (group_id,))


def add_person(group_id, name, url, ics_text):
    # the code is shown to the person once; only its hash is stored
    code = secrets.token_urlsafe(CODE_BYTES)
    sql = "INSERT INTO people (group_id, name, url, ics_text, code_hash) VALUES (?, ?, ?, ?, ?)"
    query(sql, (group_id, name, url, ics_text, hash_code(code)))
    return code


def get_person_by_code(code):
    rows = query("SELECT * FROM people WHERE code_hash = ?", (hash_code(code),))
    return rows[0] if rows else None


def update_person(person_id, url, ics_text):
    query("UPDATE people SET url = ?, ics_text = ? WHERE id = ?", (url, ics_text, person_id))


def delete_person(person_id):
    query("DELETE FROM people WHERE id = ?", (person_id,))


def set_admin_code(group_id):
    # for groups made before admin codes existed (see make_admin.py)
    admin_code = secrets.token_urlsafe(CODE_BYTES)
    query("UPDATE groups SET admin_hash = ? WHERE id = ?", (hash_code(admin_code), group_id))
    return admin_code


def get_group_by_admin(admin_code):
    rows = query("SELECT * FROM groups WHERE admin_hash = ?", (hash_code(admin_code),))
    return rows[0] if rows else None


def get_person(person_id):
    rows = query("SELECT * FROM people WHERE id = ?", (person_id,))
    return rows[0] if rows else None


def rename_person(person_id, name):
    query("UPDATE people SET name = ? WHERE id = ?", (name, person_id))
