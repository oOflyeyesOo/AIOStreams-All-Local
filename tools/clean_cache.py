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

    if include_poster_cache:
        purge_targets.append(("Posters+ Image Cache", repo_root / "data" / "postersplus"))

    for label, target_path in purge_targets:
        if not target_path.exists():
            continue

        size = get_dir_size(target_path)
        file_count = 0
        try:
            file_count = sum(1 for p in target_path.rglob("*") if p.is_file())
        except Exception:
            pass

        if file_count == 0 and size == 0:
            continue

        total_bytes += size
        total_files += file_count

        if not dry_run:
            try:
                for item in target_path.iterdir():
                    if item.is_file() or item.is_symlink():
                        try:
                            item.unlink()
                        except Exception:
                            pass
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
            except Exception as e:
                details.append({
                    "target": label,
                    "path": str(target_path),
                    "size_bytes": size,
                    "file_count": file_count,
                    "status": f"partial: {e}"
                })
                continue

        details.append({
            "target": label,
            "path": str(target_path),
            "size_bytes": size,
            "file_count": file_count,
            "status": "dry-run" if dry_run else "cleaned"
        })

    # Also clean Python bytecode caches
    pycache_count = 0
    pycache_bytes = 0
    for pyc_dir in repo_root.rglob("__pycache__"):
        if ".git" in pyc_dir.parts:
            continue
        c_size = get_dir_size(pyc_dir)
        c_count = sum(1 for p in pyc_dir.glob("*.pyc") if p.is_file())
        pycache_bytes += c_size
        pycache_count += c_count
        if not dry_run:
            shutil.rmtree(pyc_dir, ignore_errors=True)

    if pycache_count > 0:
        total_bytes += pycache_bytes
        total_files += pycache_count
        details.append({
            "target": "Python Bytecode Cache (__pycache__)",
            "path": "repo_root/**/__pycache__",
            "size_bytes": pycache_bytes,
            "file_count": pycache_count,
            "status": "dry-run" if dry_run else "cleaned"
        })

    freed_mb = round(total_bytes / (1024 * 1024), 2)
    freed_gb = round(total_bytes / (1024 * 1024 * 1024), 2)

    return {
        "success": True,
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
