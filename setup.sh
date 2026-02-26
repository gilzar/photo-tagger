#!/bin/bash
# Setup script for Photo Tagger
set -e

echo "=== Photo Tagger Setup ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required. Install it first."
    exit 1
fi

# Check Ollama
if ! command -v ollama &> /dev/null; then
    echo "Warning: Ollama not found in PATH. Make sure it's running at http://localhost:11434"
else
    echo "✓ Ollama found"
fi

# Check ffmpeg (for video support)
if ! command -v ffmpeg &> /dev/null; then
    echo "Warning: ffmpeg not found. Video analysis won't work."
    echo "  Install: brew install ffmpeg"
else
    echo "✓ ffmpeg found"
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Quick Start:"
echo "  1. Make sure Ollama is running with a vision model:"
echo "     ollama pull llava"
echo "     ollama serve"
echo ""
echo "  2. Scan your photos directory:"
echo "     python3 cli.py scan"
echo ""
echo "  3. Run AI analysis:"
echo "     python3 cli.py analyze"
echo ""
echo "  4. Start the web UI:"
echo "     python3 cli.py web"
echo "     Then open http://127.0.0.1:8899"
echo ""
echo "  5. Search from CLI:"
echo "     python3 cli.py search sunset beach"
echo ""
echo "  6. Review duplicates/junk:"
echo "     python3 cli.py duplicates"
echo "     python3 cli.py junk"
