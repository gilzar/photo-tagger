"""Tests for database.py."""
import json
import sqlite3

import pytest

import database


# ── init_db ──────────────────────────────────────────────────────────────────


def test_init_db_creates_tables(db_conn):
    tables = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in tables}
    assert "files" in names
    assert "files_fts" in names

    # Triggers
    triggers = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    trigger_names = {r["name"] for r in triggers}
    assert "files_ai" in trigger_names
    assert "files_ad" in trigger_names
    assert "files_au" in trigger_names

    # Indexes
    indexes = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    idx_names = {r["name"] for r in indexes}
    assert "idx_file_hash" in idx_names
    assert "idx_phash" in idx_names
    assert "idx_file_type" in idx_names


# ── get_connection ───────────────────────────────────────────────────────────


def test_get_connection_contextmanager(tmp_path):
    db_path = str(tmp_path / "test.db")
    database.init_db(db_path).close()

    with database.get_connection(db_path) as conn:
        conn.execute("INSERT INTO files (filepath, filename, file_type) VALUES (?, ?, ?)",
                      ("/a.jpg", "a.jpg", "image"))

    # Row should persist after commit
    verify = sqlite3.connect(db_path)
    verify.row_factory = sqlite3.Row
    row = verify.execute("SELECT * FROM files WHERE filepath = '/a.jpg'").fetchone()
    assert row is not None
    assert row["filename"] == "a.jpg"
    verify.close()


def test_get_connection_rollback_on_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    database.init_db(db_path).close()

    with pytest.raises(ValueError):
        with database.get_connection(db_path) as conn:
            conn.execute("INSERT INTO files (filepath, filename, file_type) VALUES (?, ?, ?)",
                          ("/b.jpg", "b.jpg", "image"))
            raise ValueError("boom")

    verify = sqlite3.connect(db_path)
    row = verify.execute("SELECT * FROM files WHERE filepath = '/b.jpg'").fetchone()
    assert row is None
    verify.close()


# ── upsert_file ──────────────────────────────────────────────────────────────


def test_upsert_insert(db_conn, sample_file_data):
    file_id = database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()
    assert file_id > 0


def test_upsert_update(db_conn, sample_file_data):
    id1 = database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    updated = {**sample_file_data, "description": "Updated description"}
    id2 = database.upsert_file(db_conn, updated)
    db_conn.commit()

    assert id1 == id2
    row = db_conn.execute("SELECT description FROM files WHERE id = ?", (id1,)).fetchone()
    assert row["description"] == "Updated description"


def test_upsert_serializes_lists(db_conn, sample_file_data):
    database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    row = db_conn.execute("SELECT tags FROM files WHERE filepath = ?",
                          (sample_file_data["filepath"],)).fetchone()
    # tags should be stored as a JSON string
    assert row["tags"] == json.dumps(["test", "photo"])


# ── search_files ─────────────────────────────────────────────────────────────


def test_search_files_empty_query(db_conn, sample_file_data):
    database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    results = database.search_files(db_conn, "")
    assert len(results) == 1


def test_search_files_with_query(db_conn, sample_file_data):
    database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    results = database.search_files(db_conn, "test_photo")
    assert len(results) >= 1
    assert results[0]["filepath"] == sample_file_data["filepath"]


def test_search_files_type_filter(db_conn, sample_file_data):
    database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    assert len(database.search_files(db_conn, "", file_type="image")) == 1
    assert len(database.search_files(db_conn, "", file_type="video")) == 0


# ── get_stats ────────────────────────────────────────────────────────────────


def test_get_stats_empty_db(db_conn):
    stats = database.get_stats(db_conn)
    assert stats["total_files"] == 0
    assert stats["images"] == 0
    assert stats["videos"] == 0
    assert stats["total_size"] == 0


def test_get_stats_with_data(db_conn, sample_file_data):
    database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    stats = database.get_stats(db_conn)
    assert stats["total_files"] == 1
    assert stats["images"] == 1
    assert stats["total_size"] == sample_file_data["file_size"]


# ── get_file_by_id ───────────────────────────────────────────────────────────


def test_get_file_by_id(db_conn, sample_file_data):
    file_id = database.upsert_file(db_conn, sample_file_data)
    db_conn.commit()

    row = database.get_file_by_id(db_conn, file_id)
    assert row is not None
    assert row["filepath"] == sample_file_data["filepath"]

    assert database.get_file_by_id(db_conn, 9999) is None


# ── get_all_tags ─────────────────────────────────────────────────────────────


def test_get_all_tags(db_conn, sample_file_data):
    database.upsert_file(db_conn, sample_file_data)
    # Second file shares one tag
    data2 = {**sample_file_data, "filepath": "/other.jpg", "filename": "other.jpg",
             "tags": ["photo", "landscape"]}
    database.upsert_file(db_conn, data2)
    db_conn.commit()

    tags = database.get_all_tags(db_conn)
    tag_dict = dict(tags)
    assert tag_dict["photo"] == 2
    assert tag_dict["test"] == 1
    assert tag_dict["landscape"] == 1


# ── get_duplicates ───────────────────────────────────────────────────────────


def test_get_duplicates(db_conn, sample_file_data):
    orig_id = database.upsert_file(db_conn, sample_file_data)
    dup_data = {**sample_file_data, "filepath": "/dup.jpg", "filename": "dup.jpg",
                "is_duplicate": 1, "duplicate_of": orig_id}
    database.upsert_file(db_conn, dup_data)
    db_conn.commit()

    dups = database.get_duplicates(db_conn)
    assert len(dups) == 1
    assert dups[0]["original_filepath"] == sample_file_data["filepath"]


# ── get_junk_files ───────────────────────────────────────────────────────────


def test_get_junk_files(db_conn, sample_file_data):
    junk_data = {**sample_file_data, "filepath": "/junk.jpg", "filename": "junk.jpg",
                 "is_junk": 1, "junk_reason": "very small (100 bytes)"}
    database.upsert_file(db_conn, junk_data)
    db_conn.commit()

    junks = database.get_junk_files(db_conn)
    assert len(junks) == 1
    assert junks[0]["junk_reason"] == "very small (100 bytes)"
