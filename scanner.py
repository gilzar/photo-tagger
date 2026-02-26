"""
Core scanner: discovers files, extracts metadata, detects duplicates/junk.
"""
import os
import hashlib
import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags
import imagehash

import config
import database

logger = logging.getLogger(__name__)


def discover_files(scan_dir: str):
    """Walk directory and yield media file paths."""
    scan_dir = os.path.expanduser(scan_dir)
    all_extensions = config.IMAGE_EXTENSIONS | config.VIDEO_EXTENSIONS

    for root, dirs, files in os.walk(scan_dir):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.startswith("."):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in all_extensions:
                yield os.path.join(root, fname)


def get_file_type(filepath: str) -> str:
    """Determine if file is image or video."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in config.IMAGE_EXTENSIONS:
        return "image"
    elif ext in config.VIDEO_EXTENSIONS:
        return "video"
    return "unknown"


def compute_file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of file contents."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def compute_perceptual_hash(filepath: str) -> str | None:
    """Compute perceptual hash for an image (for near-duplicate detection)."""
    try:
        img = Image.open(filepath)
        phash = imagehash.phash(img)
        return str(phash)
    except (OSError, Image.UnidentifiedImageError, ValueError) as e:
        logger.warning("Perceptual hash failed for %s: %s", filepath, e)
        return None


def extract_exif(filepath: str) -> dict:
    """Extract EXIF metadata from an image."""
    try:
        img = Image.open(filepath)
        exif_raw = img._getexif()
        if not exif_raw:
            return {}
        exif = {}
        for tag_id, value in exif_raw.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            # Convert bytes and other non-serializable types
            if isinstance(value, bytes):
                try:
                    value = value.decode("utf-8", errors="replace")
                except (UnicodeDecodeError, AttributeError):
                    value = str(value)[:100]
            elif isinstance(value, (tuple, list)):
                value = str(value)
            elif not isinstance(value, (str, int, float, bool)):
                value = str(value)[:200]
            exif[tag_name] = value
        return exif
    except (OSError, Image.UnidentifiedImageError, AttributeError) as e:
        logger.warning("EXIF extraction failed for %s: %s", filepath, e)
        return {}


def extract_image_metadata(filepath: str) -> dict:
    """Extract full metadata from an image file."""
    stat = os.stat(filepath)
    data = {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "original_filename": os.path.basename(filepath),
        "file_type": "image",
        "file_size": stat.st_size,
        "created_date": datetime.fromtimestamp(stat.st_birthtime if hasattr(stat, "st_birthtime") else stat.st_ctime).isoformat(),
        "modified_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "scan_date": datetime.now().isoformat(),
    }

    # Image dimensions
    try:
        with Image.open(filepath) as img:
            data["width"], data["height"] = img.size
    except (OSError, Image.UnidentifiedImageError) as e:
        logger.warning("Could not read image dimensions for %s: %s", filepath, e)

    # EXIF
    exif = extract_exif(filepath)
    if exif:
        data["exif_data"] = json.dumps(exif)

    # Hashes
    data["file_hash"] = compute_file_hash(filepath)
    data["perceptual_hash"] = compute_perceptual_hash(filepath)

    return data


def extract_video_metadata(filepath: str) -> dict:
    """Extract metadata from a video file."""
    stat = os.stat(filepath)
    data = {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "original_filename": os.path.basename(filepath),
        "file_type": "video",
        "file_size": stat.st_size,
        "created_date": datetime.fromtimestamp(stat.st_birthtime if hasattr(stat, "st_birthtime") else stat.st_ctime).isoformat(),
        "modified_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "scan_date": datetime.now().isoformat(),
    }

    # Try to get video dimensions with ffprobe
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", filepath],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    data["width"] = int(stream.get("width", 0))
                    data["height"] = int(stream.get("height", 0))
                    break
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as e:
        logger.warning("ffprobe failed for %s: %s", filepath, e)
    except FileNotFoundError:
        logger.warning("ffprobe not found — install ffmpeg to extract video metadata")

    data["file_hash"] = compute_file_hash(filepath)
    return data


def extract_video_frames(filepath: str, num_frames: int = 3) -> list[str]:
    """Extract sample frames from video for AI analysis. Returns list of temp image paths."""
    frames = []
    created_temps = []  # Track all temp files for cleanup on error
    try:
        # Get video duration
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            capture_output=True, text=True, timeout=30
        )
        try:
            duration = float(result.stdout.strip()) if result.returncode == 0 else 10.0
        except (ValueError, AttributeError):
            duration = 10.0

        for i in range(num_frames):
            timestamp = duration * (i + 1) / (num_frames + 1)
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            created_temps.append(tmp.name)
            subprocess.run(
                ["ffmpeg", "-ss", str(timestamp), "-i", filepath,
                 "-vframes", "1", "-y", "-q:v", "2", tmp.name],
                capture_output=True, timeout=30
            )
            if os.path.getsize(tmp.name) > 0:
                frames.append(tmp.name)
            else:
                os.unlink(tmp.name)
                created_temps.remove(tmp.name)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
        logger.warning("Video frame extraction failed for %s: %s", filepath, e)
        # Clean up any temp files that weren't added to frames
        for tmp_path in created_temps:
            if tmp_path not in frames:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    except FileNotFoundError:
        logger.warning("ffmpeg/ffprobe not found — install ffmpeg to extract video frames")
    return frames


def detect_junk(filepath: str, file_size: int) -> tuple[bool, str]:
    """Check if a file looks like junk."""
    reasons = []
    fname = os.path.basename(filepath).lower()

    # Tiny files
    if file_size < config.JUNK_SIZE_THRESHOLD:
        reasons.append(f"very small ({file_size} bytes)")

    # Common junk patterns
    junk_patterns = ["thumb", "thumbnail", ".ds_store", "desktop.ini", "thumbs.db"]
    if any(p in fname for p in junk_patterns):
        reasons.append("thumbnail/system file pattern")

    # Corrupted images
    ext = os.path.splitext(filepath)[1].lower()
    if ext in config.IMAGE_EXTENSIONS:
        try:
            with Image.open(filepath) as img:
                img.verify()
        except (OSError, Image.UnidentifiedImageError, SyntaxError):
            reasons.append("corrupted or unreadable image")

    if reasons:
        return True, "; ".join(reasons)
    return False, ""


def find_duplicates(conn):
    """Detect duplicate files using file hash and perceptual hash."""
    # Exact duplicates (same file hash)
    rows = conn.execute("""
        SELECT file_hash, GROUP_CONCAT(id) as ids
        FROM files
        WHERE file_hash IS NOT NULL
        GROUP BY file_hash
        HAVING COUNT(*) > 1
    """).fetchall()

    for row in rows:
        ids = [int(x) for x in row["ids"].split(",")]
        original_id = ids[0]  # Keep the first one as "original"
        for dup_id in ids[1:]:
            conn.execute("""
                UPDATE files SET is_duplicate = 1, duplicate_of = ?
                WHERE id = ?
            """, (original_id, dup_id))

    # Near-duplicates for images (perceptual hash)
    phash_rows = conn.execute("""
        SELECT id, perceptual_hash FROM files
        WHERE perceptual_hash IS NOT NULL
        AND is_duplicate = 0
        AND file_type = 'image'
    """).fetchall()

    # Compare perceptual hashes (hamming distance)
    phash_list = [(r["id"], imagehash.hex_to_hash(r["perceptual_hash"])) for r in phash_rows]
    for i, (id_a, hash_a) in enumerate(phash_list):
        for j, (id_b, hash_b) in enumerate(phash_list):
            if j <= i:
                continue
            distance = hash_a - hash_b
            if distance <= 8:  # Threshold for "near duplicate"
                conn.execute("""
                    UPDATE files SET is_duplicate = 1, duplicate_of = ?
                    WHERE id = ? AND is_duplicate = 0
                """, (id_a, id_b))

    conn.commit()


def scan_directory(scan_dir: str = None, progress_callback=None):
    """
    Main scan function: discover files, extract metadata, detect junk/duplicates.
    Returns stats dict.
    """
    scan_dir = scan_dir or config.SCAN_DIR
    conn = database.init_db()

    files_found = 0
    files_processed = 0
    errors = []

    all_files = list(discover_files(scan_dir))
    total = len(all_files)

    for i, filepath in enumerate(all_files):
        try:
            files_found += 1
            ftype = get_file_type(filepath)

            if ftype == "image":
                data = extract_image_metadata(filepath)
            elif ftype == "video":
                data = extract_video_metadata(filepath)
            else:
                continue

            # Check for junk
            is_junk, junk_reason = detect_junk(filepath, data.get("file_size", 0))
            data["is_junk"] = 1 if is_junk else 0
            data["junk_reason"] = junk_reason if is_junk else None

            database.upsert_file(conn, data)
            files_processed += 1

            if progress_callback and (i + 1) % 10 == 0:
                progress_callback(i + 1, total)

        except Exception as e:
            logger.warning("Failed to process %s: %s", filepath, e)
            errors.append(f"{filepath}: {str(e)}")

        # Commit in batches
        if (i + 1) % config.BATCH_SIZE == 0:
            conn.commit()

    conn.commit()

    # Detect duplicates
    if progress_callback:
        progress_callback(total, total, "Detecting duplicates...")
    find_duplicates(conn)

    stats = {
        "files_found": files_found,
        "files_processed": files_processed,
        "errors": errors,
    }
    stats.update(database.get_stats(conn))
    conn.close()
    return stats
