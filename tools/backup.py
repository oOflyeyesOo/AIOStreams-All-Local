#!/usr/bin/env python3
"""AIO Local Stack Fast Backup & Restore Utility

Creates clean, lightweight, compressed archives (.tar.gz) of:
  • PostgreSQL database cluster (atomic pg_dumpall of zilean, mediafusion, aiometadata, sootio)
  • Primary SQLite databases (AIOStreams db.sqlite, Comet comet.db, Debrid Search)
  • Essential service configurations (Prowlarr, SlickSync, InfiniDysk, Stremio Web)
  • Environment settings (.env)

Excludes ephemeral cache directories (stremthru hashlists, redis dumps, stremthru.db cache)
by default so backups complete in ~2-3 seconds and remain small and easily portable (~10-20 MB).
Pass --include-cache to include heavy proxy scrape caches (e.g. stremthru.db).
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

# Force UTF-8 on Windows consoles to prevent charmap encoding errors
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Directories and patterns to exclude from backups (ephemeral/recreatable caches)
EXCLUDE_PATTERNS = {
    "hashlists",
    "cache",
    "imdb",
    "anime-database",
    "id-mappings",
    "scene-mappings",
    "seadex",
    "postgres",
    "redis",
    ".git"
}


def get_project_root() -> Path:
    """Resolve the root folder of the AIO stack."""
    cwd = Path.cwd().resolve()
    if (cwd / "docker-compose.yml").is_file():
        return cwd
    script_parent = Path(__file__).resolve().parent.parent
    if (script_parent / "docker-compose.yml").is_file():
        return script_parent
    return cwd


def dump_postgres(dump_file: Path) -> bool:
    """Attempt an atomic pg_dumpall from the shared-postgres container."""
    try:
        res = subprocess.run(
            ["docker", "exec", "shared-postgres", "pg_dumpall", "-U", "postgres", "--clean"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=60
        )
        if res.returncode == 0 and res.stdout:
            dump_file.write_bytes(res.stdout)
            return True
    except Exception:
        pass
    return False


def restore_postgres(dump_file: Path) -> bool:
    """Attempt to restore a pg_dumpall SQL dump into shared-postgres."""
    try:
        if not dump_file.is_file():
            return False
        sql_data = dump_file.read_bytes()
        res = subprocess.run(
            ["docker", "exec", "-i", "shared-postgres", "psql", "-U", "postgres", "-d", "postgres"],
            input=sql_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120
        )
        return res.returncode == 0
    except Exception:
        return False


def create_backup(output_dir: Path = None, root: Path = None, include_cache: bool = False) -> Path:
    """Create a compressed .tar.gz backup archive."""
    if root is None:
        root = get_project_root()
    if output_dir is None:
        output_dir = root / "backups"

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = output_dir / f"aio-backup-{timestamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()

        # 1. Back up .env if present
        env_file = root / ".env"
        if env_file.is_file():
            shutil.copy2(env_file, staging_dir / ".env")

        # 2. Dump PostgreSQL cluster
        pg_dump_file = staging_dir / "postgres_cluster.sql"
        pg_ok = dump_postgres(pg_dump_file)
        if not pg_ok:
            print("  [!] Note: shared-postgres container not reachable for pg_dumpall.", flush=True)

        # 3. Back up essential configuration and database files
        data_dir = root / "data"
        staging_data = staging_dir / "data"

        # Explicit list of valuable files / directories to copy:
        items_to_backup = [
            ("aiostreams/db.sqlite", False),
            ("aiostreams/aiostreams_install.json", False),
            ("aiostreams/instance-id", False),
            ("comet/comet.db", False),
            ("prowlarr/config.xml", False),
            ("debrid-search", True),
            ("slicksync", True),
            ("infinidysk", True),
            ("stremio-web/localStorage.json", False),
            ("stremio-web/aiostreams_install.json", False),
            ("postersplus", True),
            ("subsense", True)
        ]

        if include_cache:
            items_to_backup.append(("stremthru/stremthru.db", False))

        for item_rel, is_dir in items_to_backup:
            src = data_dir / item_rel
            dest = staging_data / item_rel
            if is_dir and src.is_dir():
                def filter_files(directory, contents):
                    # Filter out cache subdirs and shm/wal files
                    return [c for c in contents if c in EXCLUDE_PATTERNS or c.endswith(("-shm", "-wal"))]
                shutil.copytree(src, dest, ignore=filter_files, dirs_exist_ok=True)
            elif not is_dir and src.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

        # 4. Pack into tar.gz
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in staging_dir.iterdir():
                tar.add(item, arcname=item.name)

    return archive_path


def restore_backup(archive_path: Path, root: Path = None) -> bool:
    """Restore from a compressed .tar.gz backup archive."""
    if root is None:
        root = get_project_root()
    archive_path = Path(archive_path).resolve()
    if not archive_path.is_file():
        print(f"[!] Error: Archive not found at {archive_path}", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(tmp_path)

        # 1. Restore .env
        env_backup = tmp_path / ".env"
        if env_backup.is_file():
            shutil.copy2(env_backup, root / ".env")
            print("  [✓] Restored .env")

        # 2. Restore data directory
        data_backup = tmp_path / "data"
        if data_backup.is_dir():
            target_data = root / "data"
            target_data.mkdir(parents=True, exist_ok=True)
            shutil.copytree(data_backup, target_data, dirs_exist_ok=True)
            print("  [✓] Restored data/ directory contents (SQLite DBs & configs)")

        # 3. Restore PostgreSQL SQL dump if present
        sql_dump = tmp_path / "postgres_cluster.sql"
        if sql_dump.is_file():
            print("  [i] Restoring PostgreSQL database cluster...")
            if restore_postgres(sql_dump):
                print("  [✓] PostgreSQL databases restored successfully!")
            else:
                print("  [!] Note: Could not pipe SQL directly into shared-postgres (container may be stopped).")
                print(f"      Saved SQL dump to {root / 'backups' / 'postgres_restore.sql'} for manual import.")
                (root / "backups").mkdir(exist_ok=True)
                shutil.copy2(sql_dump, root / "backups" / "postgres_restore.sql")

    return True


def list_backups(root: Path = None):
    """List available backups in the backups/ folder."""
    if root is None:
        root = get_project_root()
    backup_dir = root / "backups"
    if not backup_dir.is_dir():
        print("No backups directory found.")
        return

    archives = sorted(backup_dir.glob("aio-backup-*.tar.gz"), reverse=True)
    if not archives:
        print("No backup archives found in backups/.")
        return

    print("\nAvailable AIO Stack Backups:")
    print("-" * 65)
    for arch in archives:
        size_mb = arch.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(arch.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  • {arch.name}  ({size_mb:.2f} MB, {mtime})")
    print("-" * 65)


def main():
    parser = argparse.ArgumentParser(description="AIO Local Stack Fast Backup & Restore Utility")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup", action="store_true", help="Create a clean, lightweight stack backup")
    group.add_argument("--restore", type=str, metavar="ARCHIVE_FILE", help="Restore stack from a backup archive")
    group.add_argument("--list", action="store_true", help="List existing backups in backups/ folder")
    parser.add_argument("--include-cache", action="store_true", help="Include heavy proxy scrape caches (e.g. stremthru.db)")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to save the backup")

    args = parser.parse_args()
    root = get_project_root()

    if args.backup:
        print(f"[i] Backing up AIO Local Stack from {root}...", flush=True)
        out_dir = Path(args.output_dir) if args.output_dir else root / "backups"
        archive = create_backup(out_dir, root, include_cache=args.include_cache)
        size_mb = archive.stat().st_size / (1024 * 1024)
        print(f"[✓] Backup created successfully:\n    {archive} ({size_mb:.2f} MB)", flush=True)

    elif args.restore:
        archive_file = Path(args.restore)
        print(f"[i] Restoring AIO Local Stack from {archive_file}...", flush=True)
        if restore_backup(archive_file, root):
            print(f"[✓] Restore completed successfully! Restart stack with 'docker compose up -d'.", flush=True)
        else:
            print("[✗] Restore failed.", file=sys.stderr)
            sys.exit(1)

    elif args.list:
        list_backups(root)


if __name__ == "__main__":
    main()
