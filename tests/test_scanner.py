"""Tests for scanner.py."""
import hashlib
import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

import scanner
import database


# ── get_file_type ────────────────────────────────────────────────────────────


def test_get_file_type_image():
    assert scanner.get_file_type("photo.jpg") == "image"
    assert scanner.get_file_type("pic.PNG") == "image"
    assert scanner.get_file_type("file.heic") == "image"


def test_get_file_type_video():
    assert scanner.get_file_type("clip.mp4") == "video"
    assert scanner.get_file_type("movie.MOV") == "video"
    assert scanner.get_file_type("vid.mkv") == "video"


def test_get_file_type_unknown():
    assert scanner.get_file_type("notes.txt") == "unknown"
    assert scanner.get_file_type("data.csv") == "unknown"


# ── discover_files ───────────────────────────────────────────────────────────


def test_discover_files(tmp_path):
    # Create media files
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "video.mp4").write_bytes(b"\x00")
    # Non-media
    (tmp_path / "notes.txt").write_text("hello")
    # Hidden file
    (tmp_path / ".hidden.jpg").write_bytes(b"\xff\xd8")
    # Hidden dir
    hidden_dir = tmp_path / ".hidden_dir"
    hidden_dir.mkdir()
    (hidden_dir / "secret.jpg").write_bytes(b"\xff\xd8")

    found = list(scanner.discover_files(str(tmp_path)))
    basenames = [os.path.basename(f) for f in found]
    assert "photo.jpg" in basenames
    assert "video.mp4" in basenames
    assert "notes.txt" not in basenames
    assert ".hidden.jpg" not in basenames
    assert "secret.jpg" not in basenames


# ── compute_file_hash ────────────────────────────────────────────────────────


def test_compute_file_hash(tmp_path):
    f = tmp_path / "data.bin"
    content = b"deterministic content for hashing"
    f.write_bytes(content)

    result = scanner.compute_file_hash(str(f))
    expected = hashlib.sha256(content).hexdigest()
    assert result == expected


# ── compute_perceptual_hash ──────────────────────────────────────────────────


def test_compute_perceptual_hash(sample_image):
    result = scanner.compute_perceptual_hash(sample_image)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) == 16  # phash hex string length


def test_compute_perceptual_hash_invalid(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert scanner.compute_perceptual_hash(str(bad)) is None


# ── extract_exif ─────────────────────────────────────────────────────────────


def test_extract_exif_no_exif(sample_rgba_image):
    """PNG files typically have no EXIF."""
    exif = scanner.extract_exif(sample_rgba_image)
    assert exif == {}


# ── extract_image_metadata ───────────────────────────────────────────────────


def test_extract_image_metadata(sample_image):
    data = scanner.extract_image_metadata(sample_image)
    assert data["filepath"] == sample_image
    assert data["filename"] == os.path.basename(sample_image)
    assert data["file_type"] == "image"
    assert data["file_size"] > 0
    assert data["width"] == 100
    assert data["height"] == 100
    assert "file_hash" in data
    assert "scan_date" in data


# ── extract_video_metadata ───────────────────────────────────────────────────


def test_extract_video_metadata(tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 1000)

    ffprobe_output = {
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ]
    }
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = __import__("json").dumps(ffprobe_output)

    with patch("scanner.subprocess.run", return_value=mock_result):
        data = scanner.extract_video_metadata(str(video))

    assert data["file_type"] == "video"
    assert data["width"] == 1920
    assert data["height"] == 1080
    assert "file_hash" in data


# ── extract_video_frames ────────────────────────────────────────────────────


def test_extract_video_frames(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 500)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        # ffprobe duration call
        if "ffprobe" in cmd:
            result.stdout = "10.0"
            return result
        # ffmpeg frame extraction — write dummy content to the output path
        output_path = cmd[-1]
        with open(output_path, "wb") as f:
            f.write(b"\xff\xd8fake frame data")
        return result

    with patch("scanner.subprocess.run", side_effect=fake_run):
        frames = scanner.extract_video_frames(str(video), num_frames=2)

    assert len(frames) == 2
    for fp in frames:
        assert os.path.exists(fp)
        os.unlink(fp)


def test_extract_video_frames_cleanup_on_error(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 500)

    call_count = 0

    def fake_run(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.returncode = 0
        if "ffprobe" in cmd:
            result.stdout = "10.0"
            return result
        # First ffmpeg succeeds, second raises
        if call_count == 2:
            output_path = cmd[-1]
            with open(output_path, "wb") as f:
                f.write(b"\xff\xd8data")
            return result
        raise subprocess.SubprocessError("ffmpeg crashed")

    with patch("scanner.subprocess.run", side_effect=fake_run):
        frames = scanner.extract_video_frames(str(video), num_frames=2)

    # Should have at most 1 frame; any temp files from failed extractions cleaned up
    assert len(frames) <= 1
    for fp in frames:
        os.unlink(fp)


# ── detect_junk ──────────────────────────────────────────────────────────────


def test_detect_junk_small_file(sample_image):
    is_junk, reason = scanner.detect_junk(sample_image, 500)
    assert is_junk is True
    assert "very small" in reason


def test_detect_junk_thumbnail_name(tmp_path):
    thumb = tmp_path / "thumbnail_001.jpg"
    img = Image.new("RGB", (50, 50), color=(0, 0, 0))
    img.save(str(thumb), format="JPEG")

    is_junk, reason = scanner.detect_junk(str(thumb), 100_000)
    assert is_junk is True
    assert "thumbnail" in reason.lower()


def test_detect_junk_clean_file(sample_image):
    is_junk, reason = scanner.detect_junk(sample_image, 100_000)
    assert is_junk is False
    assert reason == ""


# ── find_duplicates ──────────────────────────────────────────────────────────


def test_find_duplicates(db_conn):
    data1 = {
        "filepath": "/a.jpg", "filename": "a.jpg", "file_type": "image",
        "file_hash": "samehash", "file_size": 1000,
    }
    data2 = {
        "filepath": "/b.jpg", "filename": "b.jpg", "file_type": "image",
        "file_hash": "samehash", "file_size": 1000,
    }
    database.upsert_file(db_conn, data1)
    database.upsert_file(db_conn, data2)
    db_conn.commit()

    scanner.find_duplicates(db_conn)

    dup = db_conn.execute("SELECT * FROM files WHERE is_duplicate = 1").fetchall()
    assert len(dup) == 1
    assert dup[0]["filepath"] == "/b.jpg"
