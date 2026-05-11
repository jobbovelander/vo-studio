#!/usr/bin/env python3
"""
VO Studio – database.py v4.2
SQLite schema en helper functies.
"""

import sqlite3
from pathlib import Path

DB_PATH = None  # wordt gezet vanuit server.py

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS series (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            year        INTEGER,
            archived    INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS episodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id   INTEGER NOT NULL REFERENCES series(id),
            code        TEXT NOT NULL,
            title       TEXT,
            video_file  TEXT,
            fps         INTEGER DEFAULT 25,
            status      TEXT DEFAULT 'pending',
            archived    INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS scripts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id          INTEGER NOT NULL REFERENCES episodes(id),
            name                TEXT NOT NULL,
            filename            TEXT NOT NULL,
            status              TEXT DEFAULT 'pending',
            export_sample_rate  INTEGER DEFAULT 48000,
            export_bit_depth    INTEGER DEFAULT 24,
            export_channels     INTEGER DEFAULT 1,
            created_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS takes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id       INTEGER NOT NULL REFERENCES scripts(id),
            take_index      INTEGER NOT NULL,
            original_index  INTEGER,
            timecode_in     TEXT NOT NULL,
            timecode_out    TEXT,
            seconds_in      REAL NOT NULL,
            seconds_out     REAL,
            duration        REAL,
            auto_out        INTEGER DEFAULT 0,
            text            TEXT,
            annotations     TEXT DEFAULT '[]',
            status          TEXT DEFAULT 'pending',
            displaced       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS recordings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            take_id     INTEGER NOT NULL REFERENCES takes(id),
            filename    TEXT NOT NULL,
            recorded_at TEXT DEFAULT (datetime('now')),
            displaced   INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_takes_script    ON takes(script_id);
        CREATE INDEX IF NOT EXISTS idx_recordings_take ON recordings(take_id);
        CREATE INDEX IF NOT EXISTS idx_episodes_series ON episodes(series_id);
        """)

        # Migraties — voeg nieuwe kolommen toe als ze nog niet bestaan
        for migration in [
            "ALTER TABLE scripts ADD COLUMN export_status TEXT DEFAULT NULL",
            "ALTER TABLE episodes ADD COLUMN tc_offset TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass  # kolom bestaat al, geen probleem

# ── Helpers ───────────────────────────────────────────────────────

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows):
    return [dict(r) for r in rows]

def get_series_list(include_archived=False):
    with get_db() as conn:
        q = "SELECT * FROM series"
        if not include_archived:
            q += " WHERE archived=0"
        q += " ORDER BY name, year"
        return rows_to_list(conn.execute(q).fetchall())

def get_episodes(series_id, include_archived=False):
    with get_db() as conn:
        q = "SELECT * FROM episodes WHERE series_id=?"
        if not include_archived:
            q += " AND archived=0"
        q += " ORDER BY code"
        return rows_to_list(conn.execute(q, (series_id,)).fetchall())

def get_archived_episodes(series_id):
    with get_db() as conn:
        return rows_to_list(conn.execute(
            "SELECT * FROM episodes WHERE series_id=? AND archived=1 ORDER BY code",
            (series_id,)).fetchall())

def get_scripts(episode_id):
    with get_db() as conn:
        return rows_to_list(conn.execute(
            "SELECT * FROM scripts WHERE episode_id=? ORDER BY name",
            (episode_id,)).fetchall())

def get_takes(script_id):
    with get_db() as conn:
        return rows_to_list(conn.execute(
            """SELECT t.*,
                  (SELECT filename FROM recordings
                   WHERE take_id=t.id AND displaced=0
                   ORDER BY id DESC LIMIT 1) as recorded_file,
                  (SELECT recorded_at FROM recordings
                   WHERE take_id=t.id AND displaced=0
                   ORDER BY id DESC LIMIT 1) as recorded_at
               FROM takes t
               WHERE t.script_id=? AND t.displaced=0
               ORDER BY t.take_index""",
            (script_id,)).fetchall())

def get_episode_progress(episode_id):
    with get_db() as conn:
        scripts = rows_to_list(conn.execute(
            "SELECT * FROM scripts WHERE episode_id=?", (episode_id,)).fetchall())
        result = []
        for s in scripts:
            total = conn.execute(
                "SELECT COUNT(*) FROM takes WHERE script_id=? AND displaced=0",
                (s['id'],)).fetchone()[0]
            done = conn.execute(
                """SELECT COUNT(*) FROM takes t
                   WHERE t.script_id=? AND t.displaced=0
                   AND EXISTS (
                       SELECT 1 FROM recordings r
                       WHERE r.take_id=t.id AND r.displaced=0
                   )""",
                (s['id'],)).fetchone()[0]
            s['total_takes']  = total
            s['done_takes']   = done
            s['progress_pct'] = int(done / total * 100) if total else 0
            result.append(s)
        return result

def update_script_status(script_id):
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM takes WHERE script_id=? AND displaced=0",
            (script_id,)).fetchone()[0]
        done = conn.execute(
            """SELECT COUNT(*) FROM takes t
               WHERE t.script_id=? AND t.displaced=0
               AND EXISTS (
                   SELECT 1 FROM recordings r
                   WHERE r.take_id=t.id AND r.displaced=0
               )""",
            (script_id,)).fetchone()[0]
        if total == 0:
            status = 'pending'
        elif done == total:
            status = 'done'
        elif done > 0:
            status = 'in_progress'
        else:
            status = 'pending'
        conn.execute("UPDATE scripts SET status=? WHERE id=?", (status, script_id))
    return status

def update_episode_status(episode_id):
    with get_db() as conn:
        scripts = rows_to_list(conn.execute(
            "SELECT status FROM scripts WHERE episode_id=?", (episode_id,)).fetchall())
        if not scripts:
            status = 'pending'
        elif all(s['status'] == 'done' for s in scripts):
            status = 'done'
        elif any(s['status'] in ('done', 'in_progress') for s in scripts):
            status = 'in_progress'
        else:
            status = 'pending'
        conn.execute("UPDATE episodes SET status=? WHERE id=?", (status, episode_id))
    return status
