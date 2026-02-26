"""
Configuration for the Photo/Video Tagger tool.
Adjust these settings to match your setup.
"""
import os

# --- Ollama Settings ---
OLLAMA_BASE_URL = "http://localhost:11434"

# Vision model for analyzing images (MUST be a vision-capable model)
# Options: llava, llava:13b, llava:34b, llava-llama3, bakllava, moondream
VISION_MODEL = "llava"

# Optional: text model for refining descriptions/tags (set to None to skip)
# Can use deepseek-r1:70b or any other text model
TEXT_MODEL = None  # e.g., "deepseek-r1:70b"

# --- Scan Settings ---
SCAN_DIR = os.path.expanduser("~/Pictures")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw",
    ".svg", ".ico",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp",
}

# Files smaller than this (in bytes) are flagged as potential junk
JUNK_SIZE_THRESHOLD = 10_000  # 10 KB

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(__file__), "photo_tagger.db")

# --- Web UI ---
WEB_HOST = "127.0.0.1"
WEB_PORT = 8899

# --- Processing ---
# Max dimension to resize images before sending to vision model (saves memory/time)
MAX_IMAGE_DIM = 1024

# Number of frames to extract from video for analysis
VIDEO_SAMPLE_FRAMES = 3

# Batch size for processing (how many files before committing to DB)
BATCH_SIZE = 10
