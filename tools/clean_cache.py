#!/usr/bin/env python3
"""
AIO Local Stack Ephemeral Cache & Storage Cleaner Utility
=========================================================
Safely clears multi-gigabyte scraper dumps, torrent hashlists, IMDb title dumps,
and temporary caches that accumulate in background worker volumes without affecting
user databases, configurations, or credentials.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def get_dir_size(path: Path) -> int:
    """Calculate the total size of files in a directory in bytes."""
    total = 0
    if not path.exists():
        return 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except (OSError, FileNotFoundError):
                    pass
    except Exception:
        pass
    return total


def clean_stack_cache(repo_root: Path = None, include_poster_cache: bool = False, dry_run: bool = False) -> dict:
    """
    Purge ephemeral scraper dumps and temporary cache stores.
    Returns a dictionary summarizing the actions taken and storage recovered.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    repo_root = Path(repo_root).resolve()
    details = []
    total_bytes = 0
    total_files = 0

    # Ephemeral cache paths to purge
    purge_targets = [
        ("StremThru Torrent Hashlists", repo_root / "data" / "stremthru" / "hashlists"),
        ("StremThru IMDb Dumps", repo_root / "data" / "stremthru" / "imdb"),
        ("StremThru Internal Cache", repo_root / "data" / "stremthru" / "cache"),
    ]

    errors = []
    if include_poster_cache:
        # The volume also stores databases. Purge only image files, never the volume.
        poster_root = repo_root / "data" / "postersplus"
        if poster_root.exists() and repo_root in poster_root.resolve().parents:
            images = [p for p in poster_root.rglob("*") if p.is_file() and not p.is_symlink()
                      and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}]
            for image in images:
                purge_targets.append(("Posters+ Image Cache", image))
        elif poster_root.exists():
            errors.append("Posters+ cache target escapes workspace")

    # Include bytecode only within the requested workspace.
    purge_targets.extend(("Python Bytecode Cache", p) for p in repo_root.rglob("__pycache__")
                         if ".git" not in p.parts)
    for label, target_path in purge_targets:
        if not target_path.exists():
            continue
        if repo_root not in target_path.resolve().parents or target_path.is_symlink():
            errors.append(label + ": target escapes workspace or is a symbolic link")
            continue
        size = target_path.stat().st_size if target_path.is_file() else get_dir_size(target_path)
        count = 1 if target_path.is_file() else sum(p.is_file() for p in target_path.rglob("*"))
        if not size and not count:
            continue
        failed = None
        if not dry_run:
            try:
                if target_path.is_file():
                    target_path.unlink()
                else:
                    for item in target_path.iterdir():
                        if item.is_symlink() or item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
            except OSError as error:
                failed = type(error).__name__
                errors.append(label + ": " + failed)
        remaining = 0 if not target_path.exists() else (target_path.stat().st_size if target_path.is_file() else get_dir_size(target_path))
        remaining_count = 0 if not target_path.exists() else (1 if target_path.is_file() else sum(p.is_file() for p in target_path.rglob("*")))
        recovered = size if dry_run else max(0, size - remaining)
        total_bytes += recovered
        total_files += count if dry_run else max(0, count - remaining_count)
        details.append({"target": label, "path": str(target_path), "size_bytes": recovered,
                        "file_count": count, "status": ("partial: " + failed) if failed else ("dry-run" if dry_run else "cleaned")})

    freed_mb = round(total_bytes / (1024 * 1024), 2)
    freed_gb = round(total_bytes / (1024 * 1024 * 1024), 2)

    return {
        "success": not errors,
        "errors": errors,
        "dry_run": dry_run,
        "total_bytes": total_bytes,
        "freed_mb": freed_mb,
        "freed_gb": freed_gb,
        "total_files": total_files,
        "details": details
    }


def main():
    parser = argparse.ArgumentParser(description="Purge ephemeral scraper dumps and temporary cache stores.")
    parser.add_argument("--dry-run", action="store_true", help="Calculate space to be freed without deleting anything")
    parser.add_argument("--all", action="store_true", help="Also purge image poster caches")
    parser.add_argument("--json", action="store_true", help="Output summary in JSON format")
    args = parser.parse_args()

    res = clean_stack_cache(include_poster_cache=args.all, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(res, indent=2))
        return

    mode = "[DRY-RUN] " if args.dry_run else ""
    print("\n====================================================================")
    print(f"  {mode}AIO Local Stack Storage & Cache Cleanup")
    print("====================================================================")

    if not res["details"]:
        print("[✓] Stack cache is already completely clean. No action required.\n")
        return

    for item in res["details"]:
        mb = round(item["size_bytes"] / (1024 * 1024), 2)
        print(f" • {item['target']}: {mb} MB ({item['file_count']} files) -> {item['status']}")

    print("--------------------------------------------------------------------")
    action_verb = "Calculated recoverable" if args.dry_run else "Successfully recovered"
    print(f"[✓] {action_verb}: {res['freed_mb']} MB (~{res['freed_gb']} GB) across {res['total_files']} files.\n")


if __name__ == "__main__":
    main()
