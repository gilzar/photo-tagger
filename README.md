# Photo Tagger

AI-powered photo and video tagger that uses Ollama vision models to automatically describe, tag, and organize your media library.

## Features

- **AI Analysis** — Uses Ollama vision models (llava, bakllava, moondream) to generate descriptions and tags for images and videos
- **Full-Text Search** — FTS5-powered search across descriptions, tags, and filenames
- **Duplicate Detection** — Finds exact duplicates via SHA-256 and near-duplicates via perceptual hashing
- **Junk Detection** — Flags thumbnails, system files, corrupted images, and tiny files
- **Web UI** — Browse, search, edit, and analyze files from a dark-themed web interface
- **CLI** — Full command-line interface for scanning, analyzing, searching, and managing files
- **Video Support** — Extracts frames from videos for AI analysis using ffmpeg
- **EXIF Extraction** — Reads and stores image metadata

## Supported Formats

| Images | Videos |
|--------|--------|
| jpg, jpeg, png, gif, bmp, tiff, webp, heic, heif, raw, cr2, nef, arw, svg, ico | mp4, mov, avi, mkv, wmv, flv, webm, m4v, mpg, mpeg, 3gp |

## Prerequisites

- **Python 3.8+**
- **Ollama** running locally at `http://localhost:11434` with a vision model pulled (e.g. `ollama pull llava`)
- **ffmpeg** (optional, required for video frame extraction)

## Setup

```bash
chmod +x setup.sh
./setup.sh
```

Or manually:

```bash
pip install -r requirements.txt
```

## Usage

### CLI

```bash
# Scan a directory for media files
python3 cli.py scan --dir ~/Pictures

# Run AI analysis on all unprocessed files
python3 cli.py analyze

# Analyze a specific file
python3 cli.py analyze --id 42

# Search by description, tags, or filename
python3 cli.py search "sunset beach"

# Filter by type
python3 cli.py search "cat" --type image

# List all tags
python3 cli.py tags

# Show duplicates and junk files
python3 cli.py duplicates
python3 cli.py junk

# Rename a file (with AI-suggested names)
python3 cli.py rename 42 "beach-sunset.jpg"

# Show stats
python3 cli.py stats
```

### Web UI

```bash
python3 cli.py web
```

Opens at `http://127.0.0.1:8899` with:

- Dashboard with file statistics
- Grid view with thumbnails and tags
- Full-text search with type filtering
- Tag sidebar for quick filtering
- Detail modal for editing descriptions, tags, and filenames
- Per-file AI analysis trigger
- Dedicated views for duplicates and junk files

## Configuration

Edit `config.py` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `SCAN_DIR` | `~/Pictures` | Directory to scan |
| `VISION_MODEL` | `llava` | Ollama vision model |
| `TEXT_MODEL` | `None` | Optional text model for refinement |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `WEB_PORT` | `8899` | Web UI port |
| `MAX_IMAGE_DIM` | `1024` | Max image dimension sent to AI |
| `VIDEO_SAMPLE_FRAMES` | `3` | Frames extracted per video |

## Project Structure

```
photo-tagger/
├── cli.py            # Command-line interface
├── web_ui.py         # Flask web UI with embedded frontend
├── ai_analyzer.py    # Ollama vision model integration
├── scanner.py        # File discovery, metadata extraction, duplicate/junk detection
├── database.py       # SQLite + FTS5 database layer
├── config.py         # Configuration settings
├── setup.sh          # Setup script
└── requirements.txt  # Python dependencies
```
