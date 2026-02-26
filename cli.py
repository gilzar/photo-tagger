#!/usr/bin/env python3
"""
CLI tool for Photo/Video Tagger.

Usage:
    python cli.py scan [--dir PATH]       Scan directory for media files
    python cli.py analyze [--all]         Run AI analysis on unprocessed files
    python cli.py analyze --id ID         Analyze a specific file
    python cli.py search QUERY            Search files by description/tags
    python cli.py tags                    List all tags
    python cli.py duplicates              Show duplicate files
    python cli.py junk                    Show junk files
    python cli.py stats                   Show database statistics
    python cli.py rename ID NEW_NAME      Rename a file
    python cli.py web                     Start web UI
"""
import argparse
import json
import sys
import os

import config
import database
import scanner
import ai_analyzer


def cmd_scan(args):
    """Scan directory for media files."""
    scan_dir = args.dir or config.SCAN_DIR
    print(f"Scanning: {scan_dir}")
    print("This may take a while for large directories...\n")

    def progress(current, total, msg=""):
        status = msg or f"Processing files"
        print(f"\r  {status}: {current}/{total}", end="", flush=True)

    stats = scanner.scan_directory(scan_dir, progress_callback=progress)
    print("\n")
    print("=== Scan Complete ===")
    print(f"  Files found:     {stats['files_found']}")
    print(f"  Files processed: {stats['files_processed']}")
    print(f"  Images:          {stats.get('images', 0)}")
    print(f"  Videos:          {stats.get('videos', 0)}")
    print(f"  Duplicates:      {stats.get('duplicates', 0)}")
    print(f"  Junk files:      {stats.get('junk', 0)}")
    if stats["errors"]:
        print(f"  Errors:          {len(stats['errors'])}")
        for e in stats["errors"][:5]:
            print(f"    - {e}")


def cmd_analyze(args):
    """Run AI analysis."""
    conn = database.init_db()

    if args.id:
        print(f"Analyzing file ID {args.id}...")
        result = ai_analyzer.analyze_file(conn, args.id)
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Description: {result.get('description', 'N/A')}")
            print(f"Tags: {', '.join(result.get('tags', []))}")
            if result.get("suggested_filename"):
                print(f"Suggested filename: {result['suggested_filename']}")
    else:
        print(f"Analyzing unprocessed files with {config.VISION_MODEL}...")
        print(f"Ollama URL: {config.OLLAMA_BASE_URL}")
        print("This may take a while depending on the number of files and model speed.\n")

        def progress(current, total):
            print(f"\r  Progress: {current}/{total}", end="", flush=True)

        results = ai_analyzer.analyze_all_unprocessed(conn, progress_callback=progress)
        print("\n")
        print("=== Analysis Complete ===")
        print(f"  Total to process: {results['total']}")
        print(f"  Processed:        {results['processed']}")
        print(f"  Errors:           {results['errors']}")

    conn.close()


def cmd_search(args):
    """Search files."""
    query = " ".join(args.query) if args.query else ""
    conn = database.init_db()
    results = database.search_files(conn, query, file_type=args.type)

    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} result(s):\n")
    for r in results:
        tags = ""
        try:
            tags = ", ".join(json.loads(r["tags"])) if r["tags"] else ""
        except (json.JSONDecodeError, TypeError):
            tags = r.get("tags", "") or ""
        print(f"  [{r['id']}] {r['filepath']}")
        if r["description"]:
            print(f"       {r['description'][:120]}")
        if tags:
            print(f"       Tags: {tags}")
        dup = " [DUPLICATE]" if r["is_duplicate"] else ""
        junk = " [JUNK]" if r["is_junk"] else ""
        print(f"       {r['file_type']} | {format_size(r['file_size'])}{dup}{junk}")
        print()

    conn.close()


def cmd_tags(args):
    """List all tags."""
    conn = database.init_db()
    tags = database.get_all_tags(conn)
    if not tags:
        print("No tags found. Run 'analyze' first.")
        return

    print(f"Tags ({len(tags)} unique):\n")
    for tag, count in tags:
        print(f"  {tag} ({count})")
    conn.close()


def cmd_duplicates(args):
    """Show duplicates."""
    conn = database.init_db()
    dups = database.get_duplicates(conn)
    if not dups:
        print("No duplicates found.")
        return

    print(f"Found {len(dups)} duplicate file(s):\n")
    for d in dups:
        print(f"  [{d['id']}] {d['filepath']}")
        print(f"       Duplicate of: [{d['duplicate_of']}] {d['original_filepath']}")
        print(f"       Size: {format_size(d['file_size'])}")
        print()

    print("NOTE: No files have been deleted. Review the list above and decide which to keep.")
    conn.close()


def cmd_junk(args):
    """Show junk files."""
    conn = database.init_db()
    junk = database.get_junk_files(conn)
    if not junk:
        print("No junk files found.")
        return

    print(f"Found {len(junk)} potential junk file(s):\n")
    for j in junk:
        print(f"  [{j['id']}] {j['filepath']}")
        print(f"       Reason: {j['junk_reason']}")
        print(f"       Size: {format_size(j['file_size'])}")
        print()

    print("NOTE: No files have been deleted. Review the list above and decide which to remove.")
    conn.close()


def cmd_stats(args):
    """Show statistics."""
    conn = database.init_db()
    stats = database.get_stats(conn)
    print("=== Database Statistics ===")
    print(f"  Total files:   {stats['total_files']}")
    print(f"  Images:        {stats['images']}")
    print(f"  Videos:        {stats['videos']}")
    print(f"  AI analyzed:   {stats['analyzed']}")
    print(f"  Duplicates:    {stats['duplicates']}")
    print(f"  Junk files:    {stats['junk']}")
    print(f"  Total size:    {format_size(stats['total_size'])}")
    conn.close()


def cmd_rename(args):
    """Rename a file."""
    conn = database.init_db()
    result = ai_analyzer.rename_file(conn, args.id, args.new_name)
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(f"Renamed: {result['old_path']}")
        print(f"     -> {result['new_path']}")
    conn.close()


def cmd_web(args):
    """Start web UI."""
    from web_ui import app
    print(f"Starting web UI at http://{config.WEB_HOST}:{config.WEB_PORT}")
    print("Press Ctrl+C to stop.\n")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)


def format_size(size_bytes):
    """Format bytes as human-readable size."""
    if not size_bytes:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def main():
    parser = argparse.ArgumentParser(
        description="Photo/Video Tagger - AI-powered media file organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory for media files")
    p_scan.add_argument("--dir", help="Directory to scan (default: from config)")
    p_scan.set_defaults(func=cmd_scan)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Run AI analysis on files")
    p_analyze.add_argument("--id", type=int, help="Analyze a specific file by ID")
    p_analyze.add_argument("--all", action="store_true", help="Analyze all unprocessed")
    p_analyze.set_defaults(func=cmd_analyze)

    # search
    p_search = subparsers.add_parser("search", help="Search files")
    p_search.add_argument("query", nargs="*", help="Search query")
    p_search.add_argument("--type", choices=["image", "video"], help="Filter by type")
    p_search.set_defaults(func=cmd_search)

    # tags
    p_tags = subparsers.add_parser("tags", help="List all tags")
    p_tags.set_defaults(func=cmd_tags)

    # duplicates
    p_dups = subparsers.add_parser("duplicates", help="Show duplicate files")
    p_dups.set_defaults(func=cmd_duplicates)

    # junk
    p_junk = subparsers.add_parser("junk", help="Show junk files")
    p_junk.set_defaults(func=cmd_junk)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show statistics")
    p_stats.set_defaults(func=cmd_stats)

    # rename
    p_rename = subparsers.add_parser("rename", help="Rename a file")
    p_rename.add_argument("id", type=int, help="File ID")
    p_rename.add_argument("new_name", help="New filename")
    p_rename.set_defaults(func=cmd_rename)

    # web
    p_web = subparsers.add_parser("web", help="Start web UI")
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
