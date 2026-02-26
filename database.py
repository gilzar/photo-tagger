"""
SQLite database layer with full-text search support.
"""
import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

import config


def get_db_path():
    return config.DB_PATH


def init_db(db_path=None):
    """Initialize the database schema."""
    db_path = db_path or get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Main files table
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT,
            file_type TEXT NOT NULL,  -- 'image' or 'video'
            file_size INTEGER,
            file_hash TEXT,
            perceptual_hash TEXT,
            width INTEGER,
            height INTEGER,
            created_date TEXT,
            modified_date TEXT,
            exif_data TEXT,  -- JSON
            description TEXT,
            tags TEXT,  -- JSON array
            ai_analyzed INTEGER DEFAULT 0,
            is_duplicate INTEGER DEFAULT 0,
            duplicate_of INTEGER,  -- references files.id
            is_junk INTEGER DEFAULT 0,
            junk_reason TEXT,
            scan_date TEXT,
            FOREIGN KEY (duplicate_of) REFERENCES files(id)
        )
    """)

    # Full-text search virtual table
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            filepath, filename, description, tags,
            content='files',
            content_rowid='id'
        )
    """)

    # Triggers to keep FTS in sync
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, filepath, filename, description, tags)
            VALUES (new.id, new.filepath, new.filename, new.description, new.tags);
        END
    """)

    c.execute("""
        CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, filepath, filename, description, tags)
            VALUES ('delete', old.id, old.filepath, old.filename, old.description, old.tags);
        END
    """)

    c.execute("""
        CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, filepath, filename, description, tags)
            VALUES ('delete', old.id, old.filepath, old.filename, old.description, old.tags);
            INSERT INTO files_fts(rowid, filepath, filename, description, tags)
            VALUES (new.id, new.filepath, new.filename, new.description, new.tags);
        END
    """)

    # Indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_file_hash ON files(file_hash)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_phash ON files(perceptual_hash)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_file_type ON files(file_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_is_duplicate ON files(is_duplicate)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_is_junk ON files(is_junk)")

    conn.commit()
    return conn


@contextmanager
def get_connection(db_path=None):
    """Context manager for database connections."""
    db_path = db_path or get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_file(conn, file_data: dict):
    """Insert or update a file record."""
    existing = conn.execute(
        "SELECT id FROM files WHERE filepath = ?", (file_data["filepath"],)
    ).fetchone()

    if existing:
        file_id = existing["id"]
        sets = []
        vals = []
        for k, v in file_data.items():
            if k != "filepath":
                sets.append(f"{k} = ?")
                vals.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        vals.append(file_data["filepath"])
        conn.execute(
            f"UPDATE files SET {', '.join(sets)} WHERE filepath = ?", vals
        )
        return file_id
    else:
        cols = list(file_data.keys())
        vals = []
        for v in file_data.values():
            vals.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
        placeholders = ", ".join(["?"] * len(cols))
        cur = conn.execute(
            f"INSERT INTO files ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
        return cur.lastrowid


def search_files(conn, query: str, file_type: str = None, limit: int = 100, offset: int = 0):
    """Full-text search across files."""
    if query.strip():
        # Use FTS5 search
        sql = """
            SELECT f.*, rank
            FROM files f
            JOIN files_fts fts ON f.id = fts.rowid
            WHERE files_fts MATCH ?
        """
        params = [query]
    else:
        sql = "SELECT f.*, 0 as rank FROM files f WHERE 1=1"
        params = []

    if file_type:
        sql += " AND f.file_type = ?"
        params.append(file_type)

    if query.strip():
        sql += " ORDER BY rank"
    else:
        sql += " ORDER BY f.modified_date DESC"

    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    return conn.execute(sql, params).fetchall()


def get_duplicates(conn):
    """Get all files flagged as duplicates, grouped by their original."""
    rows = conn.execute("""
        SELECT d.*, o.filepath as original_filepath, o.filename as original_filename
        FROM files d
        LEFT JOIN files o ON d.duplicate_of = o.id
        WHERE d.is_duplicate = 1
        ORDER BY d.duplicate_of, d.filepath
    """).fetchall()
    return rows


def get_junk_files(conn):
    """Get all files flagged as junk."""
    return conn.execute("""
        SELECT * FROM files WHERE is_junk = 1
        ORDER BY junk_reason, filepath
    """).fetchall()


def get_stats(conn):
    """Get summary statistics."""
    stats = {}
    stats["total_files"] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    stats["images"] = conn.execute("SELECT COUNT(*) FROM files WHERE file_type='image'").fetchone()[0]
    stats["videos"] = conn.execute("SELECT COUNT(*) FROM files WHERE file_type='video'").fetchone()[0]
    stats["analyzed"] = conn.execute("SELECT COUNT(*) FROM files WHERE ai_analyzed=1").fetchone()[0]
    stats["duplicates"] = conn.execute("SELECT COUNT(*) FROM files WHERE is_duplicate=1").fetchone()[0]
    stats["junk"] = conn.execute("SELECT COUNT(*) FROM files WHERE is_junk=1").fetchone()[0]
    size_row = conn.execute("SELECT SUM(file_size) FROM files").fetchone()
    stats["total_size"] = size_row[0] or 0
    return stats


def get_file_by_id(conn, file_id: int):
    """Get a single file by ID."""
    return conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()


def get_all_tags(conn):
    """Get all unique tags with counts."""
    rows = conn.execute("SELECT tags FROM files WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
    tag_counts = {}
    for row in rows:
        try:
            tags = json.loads(row["tags"])
            for tag in tags:
                tag = tag.strip().lower()
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    return sorted(tag_counts.items(), key=lambda x: -x[1])
