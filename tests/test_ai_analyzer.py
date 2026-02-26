"""Tests for ai_analyzer.py."""
import base64
import json
import os
from unittest.mock import patch, MagicMock

import pytest
import requests
from PIL import Image

import ai_analyzer
import database


# ── parse_ai_response ────────────────────────────────────────────────────────


def test_parse_ai_response_valid_json():
    raw = '{"description": "A sunset", "tags": ["sunset", "sky"]}'
    result = ai_analyzer.parse_ai_response(raw)
    assert result["description"] == "A sunset"
    assert result["tags"] == ["sunset", "sky"]


def test_parse_ai_response_embedded_json():
    raw = 'Here is my analysis:\n{"description": "A cat", "tags": ["cat", "animal"]}\nHope that helps!'
    result = ai_analyzer.parse_ai_response(raw)
    assert result["description"] == "A cat"
    assert "cat" in result["tags"]


def test_parse_ai_response_malformed():
    raw = "This is just some text with no JSON at all."
    result = ai_analyzer.parse_ai_response(raw)
    assert result["description"] == raw[:500]
    assert result["tags"] == []


def test_parse_ai_response_missing_keys():
    raw = '{"description": "Only a description"}'
    result = ai_analyzer.parse_ai_response(raw)
    assert result["description"] == "Only a description"
    assert result["tags"] == []
    assert result["suggested_filename"] is None


# ── image_to_base64 ─────────────────────────────────────────────────────────


def test_image_to_base64(sample_image):
    b64 = ai_analyzer.image_to_base64(sample_image)
    decoded = base64.b64decode(b64)
    # Should be valid JPEG bytes
    assert decoded[:2] == b"\xff\xd8"


def test_image_to_base64_rgba_conversion(sample_rgba_image):
    b64 = ai_analyzer.image_to_base64(sample_rgba_image)
    decoded = base64.b64decode(b64)
    # Output should be JPEG (converted from RGBA)
    assert decoded[:2] == b"\xff\xd8"


def test_image_to_base64_resize(tmp_path):
    big_path = tmp_path / "big.jpg"
    img = Image.new("RGB", (3000, 2000), color=(100, 150, 200))
    img.save(str(big_path), format="JPEG")

    b64 = ai_analyzer.image_to_base64(str(big_path), max_dim=512)
    decoded = base64.b64decode(b64)
    resized = Image.open(__import__("io").BytesIO(decoded))
    assert max(resized.size) <= 512


def test_image_to_base64_missing_file():
    with pytest.raises(FileNotFoundError):
        ai_analyzer.image_to_base64("/nonexistent/photo.jpg")


# ── analyze_with_vision ──────────────────────────────────────────────────────


def test_analyze_with_vision_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": '{"description": "A dog on a beach", "tags": ["dog", "beach"]}'
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("ai_analyzer.requests.post", return_value=mock_resp):
        result = ai_analyzer.analyze_with_vision("fakebase64")

    assert result["description"] == "A dog on a beach"
    assert "dog" in result["tags"]


def test_analyze_with_vision_connection_error():
    with patch("ai_analyzer.requests.post", side_effect=requests.exceptions.ConnectionError):
        result = ai_analyzer.analyze_with_vision("fakebase64")

    assert "Cannot connect" in result["description"]
    assert result["tags"] == []


# ── refine_with_text_model ───────────────────────────────────────────────────


def test_refine_no_text_model():
    with patch("ai_analyzer.config") as mock_config:
        mock_config.TEXT_MODEL = None
        result = ai_analyzer.refine_with_text_model("desc", ["tag1"], "file.jpg")

    assert result["description"] == "desc"
    assert result["tags"] == ["tag1"]


def test_refine_with_text_model():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "response": '{"description": "Refined desc", "tags": ["refined"], "suggested_filename": "better.jpg"}'
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("ai_analyzer.config") as mock_config, \
         patch("ai_analyzer.requests.post", return_value=mock_resp):
        mock_config.TEXT_MODEL = "deepseek-r1:70b"
        mock_config.OLLAMA_BASE_URL = "http://localhost:11434"
        result = ai_analyzer.refine_with_text_model("orig", ["t1"], "file.jpg")

    assert result["description"] == "Refined desc"
    assert "refined" in result["tags"]
    assert result["suggested_filename"] == "better.jpg"


# ── rename_file ──────────────────────────────────────────────────────────────


def test_rename_file_success(db_conn, sample_image):
    file_data = {
        "filepath": sample_image,
        "filename": os.path.basename(sample_image),
        "file_type": "image",
    }
    file_id = database.upsert_file(db_conn, file_data)
    db_conn.commit()

    result = ai_analyzer.rename_file(db_conn, file_id, "renamed_photo.jpg")
    assert result["success"] is True
    assert os.path.exists(result["new_path"])
    assert not os.path.exists(result["old_path"])


def test_rename_file_path_traversal(db_conn, sample_image):
    file_data = {
        "filepath": sample_image,
        "filename": os.path.basename(sample_image),
        "file_type": "image",
    }
    file_id = database.upsert_file(db_conn, file_data)
    db_conn.commit()

    result = ai_analyzer.rename_file(db_conn, file_id, "../escape.jpg")
    assert "error" in result
    assert "path separators" in result["error"] or "must not contain" in result["error"]


def test_rename_file_empty_name(db_conn, sample_image):
    file_data = {
        "filepath": sample_image,
        "filename": os.path.basename(sample_image),
        "file_type": "image",
    }
    file_id = database.upsert_file(db_conn, file_data)
    db_conn.commit()

    result = ai_analyzer.rename_file(db_conn, file_id, "   ")
    assert "error" in result
    assert "empty" in result["error"].lower()


def test_rename_file_preserves_extension(db_conn, sample_image):
    file_data = {
        "filepath": sample_image,
        "filename": os.path.basename(sample_image),
        "file_type": "image",
    }
    file_id = database.upsert_file(db_conn, file_data)
    db_conn.commit()

    result = ai_analyzer.rename_file(db_conn, file_id, "no_extension")
    assert result["success"] is True
    assert result["new_path"].endswith(".jpg")


def test_rename_file_not_found(db_conn):
    result = ai_analyzer.rename_file(db_conn, 9999, "whatever.jpg")
    assert "error" in result
    assert "not found" in result["error"].lower()


# ── analyze_all_unprocessed ──────────────────────────────────────────────────


def test_analyze_all_unprocessed(db_conn, sample_image):
    # Seed two unprocessed files and one junk file
    for i, name in enumerate(["a.jpg", "b.jpg", "junk.jpg"]):
        data = {
            "filepath": f"/fake/{name}",
            "filename": name,
            "file_type": "image",
            "ai_analyzed": 0,
            "is_junk": 1 if name == "junk.jpg" else 0,
        }
        database.upsert_file(db_conn, data)
    db_conn.commit()

    call_count = 0

    def mock_analyze_file(conn, file_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"description": "ok", "tags": ["t"]}
        return {"error": "File not found on disk"}

    with patch("ai_analyzer.analyze_file", side_effect=mock_analyze_file):
        results = ai_analyzer.analyze_all_unprocessed(db_conn)

    assert results["total"] == 2  # junk excluded
    assert results["processed"] == 1
    assert results["errors"] == 1
