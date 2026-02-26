"""Shared fixtures for photo-tagger tests."""
import json
import os
import sys

import pytest
from PIL import Image

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database


@pytest.fixture
def db_conn():
    """In-memory SQLite connection with schema initialized."""
    conn = database.init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def sample_image(tmp_path):
    """Create a small 100x100 RGB JPEG in tmp_path."""
    path = tmp_path / "test_photo.jpg"
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    img.save(str(path), format="JPEG")
    return str(path)


@pytest.fixture
def sample_rgba_image(tmp_path):
    """Create a small RGBA PNG for conversion tests."""
    path = tmp_path / "test_rgba.png"
    img = Image.new("RGBA", (80, 80), color=(200, 100, 50, 128))
    img.save(str(path), format="PNG")
    return str(path)


@pytest.fixture
def sample_file_data(sample_image):
    """Dict matching upsert_file() schema for seeding."""
    return {
        "filepath": sample_image,
        "filename": os.path.basename(sample_image),
        "original_filename": os.path.basename(sample_image),
        "file_type": "image",
        "file_size": os.path.getsize(sample_image),
        "file_hash": "abc123",
        "width": 100,
        "height": 100,
        "description": "A test photo",
        "tags": ["test", "photo"],
        "ai_analyzed": 0,
        "is_duplicate": 0,
        "is_junk": 0,
        "scan_date": "2026-01-01T00:00:00",
    }
