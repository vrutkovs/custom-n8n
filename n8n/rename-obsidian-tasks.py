#!/usr/bin/env python3
"""
Rename Obsidian task files from {id}.md to {sanitized_title}.md

This script scans a folder for files named with a numeric/alphanumeric Todoist ID
(e.g. 1234567890.md), reads the YAML frontmatter title field, and renames each
file to the sanitized title.

Usage:
    python rename-obsidian-tasks.py [options]

Examples:
    python rename-obsidian-tasks.py --folder /path/to/notes        # Rename files
    python rename-obsidian-tasks.py --folder /path/to/notes --dry-run  # Preview only

Requirements:
    - TODOIST_NOTES_FOLDER environment variable (or --folder argument) must be set
"""

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path

import structlog

structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log: structlog.BoundLogger = structlog.get_logger()

# Todoist IDs are long numeric strings (typically 10+ digits)
ID_FILENAME_RE = re.compile(r"^[a-zA-Z0-9]{8,}\.md$")


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    name = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", name)
    name = unicodedata.normalize("NFC", name)
    sanitized = re.sub(r"[\[\]#^|\\/:?]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_ ")
    if len(sanitized) > 200:
        sanitized = sanitized[:200].rstrip("_")
    return sanitized or "untitled"


def extract_frontmatter_field(content: str, field: str) -> str | None:
    """Extract a field value from YAML frontmatter."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    in_frontmatter = False
    for i, line in enumerate(lines):
        if i == 0:
            in_frontmatter = True
            continue
        if line.strip() == "---":
            break
        if in_frontmatter:
            m = re.match(rf'^{re.escape(field)}:\s*["\']?(.*?)["\']?\s*$', line)
            if m:
                return m.group(1).strip()

    return None


def find_id_files(folder: Path) -> list[Path]:
    """Find all files in folder whose stem looks like a Todoist ID."""
    return [p for p in folder.glob("*.md") if ID_FILENAME_RE.match(p.name)]


def rename_files(folder: Path, dry_run: bool = False) -> int:
    """Rename ID-named files to sanitized title filenames. Returns count of renames."""
    files = find_id_files(folder)
    if not files:
        log.info("No ID-named files found.", folder=str(folder))
        return 0

    log.info(f"Found {len(files)} ID-named file(s) to process.")
    renamed = 0

    for src in sorted(files):
        try:
            content = src.read_text(encoding="utf-8")
        except Exception as e:
            log.error("Failed to read file", file=str(src), error=str(e))
            continue

        title = extract_frontmatter_field(content, "title")
        if not title:
            log.warning("No title found in frontmatter, skipping", file=src.name)
            continue

        todoist_id = extract_frontmatter_field(content, "todoist_id")
        if not todoist_id:
            log.warning("No todoist_id found in frontmatter, skipping", file=src.name)
            continue

        project = extract_frontmatter_field(content, "project")
        project_prefix = f"{sanitize_filename(project)} - " if project else ""

        id_suffix = f" ({todoist_id})"
        # Filesystem limit is 255 bytes; reserve bytes for prefix, suffix, and extension
        max_title_bytes = 255 - len(project_prefix.encode()) - len(id_suffix.encode()) - len(".md".encode())
        title_stem = sanitize_filename(title)
        # Truncate by bytes, not chars, to stay within limit
        encoded = title_stem.encode()
        if len(encoded) > max_title_bytes:
            title_stem = encoded[:max_title_bytes].decode(errors="ignore").rstrip()

        dst = folder / f"{project_prefix}{title_stem}{id_suffix}.md"

        if dst == src:
            log.info("Already correctly named, skipping", file=src.name)
            continue

        if dst.exists():
            log.warning(
                "Target file already exists, skipping",
                src=src.name,
                dst=dst.name,
            )
            continue

        if dry_run:
            log.info("[dry-run] Would rename", src=src.name, dst=dst.name)
        else:
            src.rename(dst)
            log.info("Renamed", src=src.name, dst=dst.name)

        renamed += 1

    return renamed


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rename Obsidian task files from {id}.md to {sanitized_title}.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                # Use TODOIST_NOTES_FOLDER env var
  %(prog)s --folder /path/to/notes       # Rename files in given folder
  %(prog)s --folder /path/to/notes --dry-run  # Preview without renaming
        """,
    )
    parser.add_argument(
        "--folder",
        metavar="PATH",
        default=None,
        help="Folder containing the markdown files (overrides TODOIST_NOTES_FOLDER)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview renames without making any changes",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    args = parser.parse_args()

    if args.verbose:
        structlog.configure(
            processors=[structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.make_filtering_bound_logger(10),
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )

    folder_str = args.folder or os.getenv("TODOIST_NOTES_FOLDER")
    if not folder_str:
        log.error("No folder specified. Use --folder or set TODOIST_NOTES_FOLDER.")
        sys.exit(1)

    folder = Path(folder_str)
    if not folder.is_dir():
        log.error("Folder does not exist or is not a directory", folder=str(folder))
        sys.exit(1)

    count = rename_files(folder, dry_run=args.dry_run)
    action = "Would rename" if args.dry_run else "Renamed"
    log.info(f"{action} {count} file(s).")


if __name__ == "__main__":
    main()
