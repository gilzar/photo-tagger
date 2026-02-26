"""
AI analysis module: sends images to Ollama vision model for description and tagging.
"""
import os
import json
import base64
import logging
import requests
from PIL import Image
import io

import config
import database
import scanner

logger = logging.getLogger(__name__)


def image_to_base64(filepath: str, max_dim: int = None) -> str:
    """Load image, optionally resize, and convert to base64."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Image file not found: {filepath}")
    max_dim = max_dim or config.MAX_IMAGE_DIM
    img = Image.open(filepath)

    # Convert RGBA/P to RGB
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize if needed
    w, h = img.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def analyze_with_vision(image_b64: str, context: str = "") -> dict:
    """
    Send image to Ollama vision model. Returns dict with 'description' and 'tags'.
    """
    prompt = f"""Analyze this image and provide:
1. A detailed description (2-3 sentences) of what you see.
2. A list of relevant tags/keywords for searching (10-20 tags).

{f"Additional context: {context}" if context else ""}

Respond in this exact JSON format only, no other text:
{{"description": "your description here", "tags": ["tag1", "tag2", "tag3"]}}"""

    try:
        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": config.VISION_MODEL,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=120,
        )
        resp.raise_for_status()
        result_text = resp.json().get("response", "")

        # Try to parse JSON from response
        return parse_ai_response(result_text)

    except requests.exceptions.ConnectionError:
        return {"description": "[Error: Cannot connect to Ollama. Is it running?]", "tags": []}
    except Exception as e:
        return {"description": f"[Error: {str(e)}]", "tags": []}


def refine_with_text_model(description: str, tags: list, filename: str) -> dict:
    """
    Optionally refine description/tags using a text model (e.g., deepseek-r1).
    """
    if not config.TEXT_MODEL:
        return {"description": description, "tags": tags}

    prompt = f"""Given this image analysis, refine the description and tags for better searchability.

Filename: {filename}
Current description: {description}
Current tags: {json.dumps(tags)}

Improve the description to be more specific and useful.
Add any missing relevant tags and remove irrelevant ones.
Suggest a clearer filename if the current one is unclear (or keep it if it's already good).

Respond in this exact JSON format only:
{{"description": "refined description", "tags": ["tag1", "tag2"], "suggested_filename": "suggested_name.ext"}}"""

    try:
        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": config.TEXT_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=180,
        )
        resp.raise_for_status()
        result_text = resp.json().get("response", "")
        return parse_ai_response(result_text)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        logger.warning("Text model refinement failed: %s", e)
        return {"description": description, "tags": tags}


def parse_ai_response(text: str) -> dict:
    """Parse JSON from AI response, handling common formatting issues."""
    text = text.strip()

    # Try to find JSON in the response
    # Look for { ... } pattern
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        json_str = text[start:end]
        try:
            data = json.loads(json_str)
            return {
                "description": data.get("description", ""),
                "tags": data.get("tags", []),
                "suggested_filename": data.get("suggested_filename"),
            }
        except json.JSONDecodeError:
            pass

    # Fallback: treat entire response as description
    return {"description": text[:500], "tags": []}


def analyze_file(conn, file_id: int) -> dict:
    """Analyze a single file with the vision model."""
    row = database.get_file_by_id(conn, file_id)
    if not row:
        return {"error": "File not found"}

    filepath = row["filepath"]
    if not os.path.exists(filepath):
        return {"error": f"File not found on disk: {filepath}"}

    if row["file_type"] == "image":
        b64 = image_to_base64(filepath)
        result = analyze_with_vision(b64)
    elif row["file_type"] == "video":
        # Extract frames and analyze each, then combine
        frames = scanner.extract_video_frames(filepath, config.VIDEO_SAMPLE_FRAMES)
        if not frames:
            return {"error": "Could not extract frames from video"}

        descriptions = []
        all_tags = set()
        for frame_path in frames:
            try:
                b64 = image_to_base64(frame_path)
                r = analyze_with_vision(b64, context="This is a frame from a video.")
                if r.get("description"):
                    descriptions.append(r["description"])
                all_tags.update(r.get("tags", []))
            except (FileNotFoundError, OSError, Image.UnidentifiedImageError) as e:
                logger.warning("Failed to analyze video frame %s: %s", frame_path, e)
            finally:
                try:
                    os.unlink(frame_path)
                except OSError:
                    pass

        result = {
            "description": " | ".join(descriptions) if descriptions else "Could not analyze video",
            "tags": list(all_tags),
        }
    else:
        return {"error": "Unknown file type"}

    # Optionally refine with text model
    if config.TEXT_MODEL:
        refined = refine_with_text_model(
            result["description"], result["tags"], row["filename"]
        )
        result.update(refined)

    # Update database
    update_data = {
        "filepath": filepath,
        "description": result["description"],
        "tags": result.get("tags", []),
        "ai_analyzed": 1,
    }
    database.upsert_file(conn, update_data)

    # Rename file if suggested and different
    suggested = result.get("suggested_filename")
    if suggested and suggested != row["filename"]:
        result["suggested_filename"] = suggested

    conn.commit()
    return result


def analyze_all_unprocessed(conn, progress_callback=None):
    """Analyze all files that haven't been processed by AI yet."""
    rows = conn.execute(
        "SELECT id, filepath FROM files WHERE ai_analyzed = 0 AND is_junk = 0"
    ).fetchall()

    total = len(rows)
    results = {"processed": 0, "errors": 0, "total": total}

    for i, row in enumerate(rows):
        try:
            r = analyze_file(conn, row["id"])
            if "error" in r:
                results["errors"] += 1
            else:
                results["processed"] += 1
        except Exception as e:
            logger.warning("Failed to analyze file ID %d: %s", row["id"], e)
            results["errors"] += 1

        if progress_callback:
            progress_callback(i + 1, total)

    return results


def rename_file(conn, file_id: int, new_name: str) -> dict:
    """Rename a file on disk and update the database."""
    row = database.get_file_by_id(conn, file_id)
    if not row:
        return {"error": "File not found in database"}

    old_path = row["filepath"]
    if not os.path.exists(old_path):
        return {"error": "File not found on disk"}

    # Validate filename: prevent path traversal
    if os.sep in new_name or (os.altsep and os.altsep in new_name) or ".." in new_name:
        return {"error": "Invalid filename: must not contain path separators or '..'"}
    # Strip leading/trailing whitespace and reject empty names
    new_name = new_name.strip()
    if not new_name:
        return {"error": "Filename cannot be empty"}

    directory = os.path.dirname(old_path)
    # Preserve original extension if new name doesn't have one
    old_ext = os.path.splitext(old_path)[1]
    new_ext = os.path.splitext(new_name)[1]
    if not new_ext:
        new_name = new_name + old_ext

    new_path = os.path.join(directory, new_name)

    # Verify the resolved path stays within the same directory
    if os.path.dirname(os.path.abspath(new_path)) != os.path.dirname(os.path.abspath(old_path)):
        return {"error": "Invalid filename: path escapes parent directory"}

    if os.path.exists(new_path):
        return {"error": f"File already exists: {new_name}"}

    try:
        os.rename(old_path, new_path)
    except OSError as e:
        logger.error("Failed to rename %s to %s: %s", old_path, new_path, e)
        return {"error": f"Rename failed: {e}"}

    conn.execute(
        "UPDATE files SET filepath = ?, filename = ? WHERE id = ?",
        (new_path, new_name, file_id)
    )
    conn.commit()
    return {"success": True, "old_path": old_path, "new_path": new_path}
