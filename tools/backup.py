#!/usr/bin/env python3
"""AIO Local Stack Fast Backup & Restore Utility

Creates clean, lightweight, compressed archives (.tar.gz) of:
  • PostgreSQL database cluster (atomic pg_dumpall of zilean, aiometadata)
  • Primary SQLite databases (AIOStreams db.sqlite, Comet comet.db, Debrid Search)
  • Essential service configurations (Prowlarr, SlickSync, InfiniDysk, Stremio Web)
  • Environment settings (.env)

Excludes ephemeral cache directories (stremthru hashlists, redis dumps, stremthru.db cache)
by default so backups complete in ~2-3 seconds and remain small and easily portable (~10-20 MB).
Pass --include-cache to include heavy proxy scrape caches (e.g. stremthru.db).
"""

import argparse
from datetime import datetime, timezone
import os
import json
import hashlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import uuid

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
    "poster-cache",
    "logs",
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


def postgres_container():
    """Resolve only this Compose project's database; never a global container name."""
    project = os.environ.get("AIO_PROJECT_NAME")
    if project:
        command = ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
                   "--filter", "label=com.docker.compose.service=shared-postgres"]
    else:
        command = ["docker", "compose", "--project-directory", str(get_project_root()), "ps", "-q", "shared-postgres"]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=15)
    containers = result.stdout.split()
    if len(containers) != 1:
        raise RuntimeError("Expected one database in this Compose project")
    return containers[0]


def copy_consistent(source, destination):
    source, destination = Path(source), Path(destination)
    try:
        with source.open("rb") as handle:
            is_sqlite = handle.read(16) == b"SQLite format 3\x00"
        if is_sqlite:
            try:
                uri = source.resolve().as_uri() + "?mode=ro"
                db = sqlite3.connect(uri, uri=True)
                try:
                    output = sqlite3.connect(str(destination))
                    try:
                        db.backup(output)
                    finally:
                        output.close()
                finally:
                    db.close()
                return str(destination)
            except Exception:
                pass
    except Exception:
        pass
    return shutil.copy2(source, destination)


def dump_postgres(dump_file: Path) -> bool:
    """Dump application databases without dropping/recreating the connected admin role."""
    try:
        container = postgres_container()
        listing = subprocess.run(
            ["docker", "exec", container, "psql", "-U", "postgres", "-At", "-c",
             "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY datname"],
            capture_output=True, check=True, timeout=30)
        databases = listing.stdout.decode().splitlines()
        if not databases:
            return False
        chunks = []
        for database in databases:
            result = subprocess.run(
                ["docker", "exec", container, "pg_dump", "-U", "postgres", "--clean", "--if-exists",
                 "--create", "--no-owner", "--no-privileges", "--dbname", database],
                capture_output=True, check=True, timeout=120)
            chunks.append(result.stdout)
        dump_file.write_bytes(b"\n".join(chunks))
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def restore_postgres(dump_file: Path) -> bool:
    """Attempt to restore a pg_dumpall SQL dump into shared-postgres."""
    try:
        if not dump_file.is_file():
            return False
        sql_data = dump_file.read_bytes()
        res = subprocess.run(
            ["docker", "exec", "-i", postgres_container(), "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1"],
            input=sql_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120
        )
        return res.returncode == 0
    except Exception:
        return False


def create_backup(output_dir: Path = None, root: Path = None, include_cache: bool = False, keep_last: int = 5) -> Path:
    """Create a compressed .tar.gz backup archive."""
    if root is None:
        root = get_project_root()
    if output_dir is None:
        output_dir = root / "backups"

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = output_dir / f"aio-backup-{timestamp}-{uuid.uuid4().hex[:12]}.tar.gz"

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

        (staging_dir / "backup-manifest.json").write_text(json.dumps({
            "format": "aio-backup-v1", "postgresIncluded": pg_ok,
            "sqliteSnapshot": True,
        }), encoding="utf-8")

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
            ("prowlarr/prowlarr.db", False),
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
                shutil.copytree(src, dest, ignore=filter_files, dirs_exist_ok=True, copy_function=copy_consistent)
            elif not is_dir and src.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                copy_consistent(src, dest)

        # 4. Pack into tar.gz
        descriptor, pending = tempfile.mkstemp(prefix=".aio-backup-", suffix=".tmp", dir=output_dir)
        os.close(descriptor)
        try:
            with tarfile.open(pending, "w:gz") as tar:
                for item in staging_dir.iterdir():
                    tar.add(item, arcname=item.name)
            os.replace(pending, archive_path)
        finally:
            Path(pending).unlink(missing_ok=True)

    digest=hashlib.sha256()
    with archive_path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    with tarfile.open(archive_path,'r:gz') as archive:
        members={m.name:m.size for m in archive.getmembers()}
    profile_ok=all(members.get('data/aiostreams/'+item,0)>0 for item in ('db.sqlite','aiostreams_install.json'))
    status={'archive':archive_path.name,'createdAt':datetime.now(timezone.utc).isoformat(),
            'sizeBytes':archive_path.stat().st_size,'sha256':digest.hexdigest(),
            'postgresIncluded':pg_ok,'configurationIncluded':env_file.is_file(),
            'profileIncluded':profile_ok,'complete':bool(pg_ok and env_file.is_file() and profile_ok)}
    descriptor, pending = tempfile.mkstemp(prefix='.backup-status-',dir=output_dir)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:json.dump(status,output)
        os.replace(pending,archive_path.with_suffix(archive_path.suffix+'.json'))
    finally:Path(pending).unlink(missing_ok=True)
    if keep_last > 0:
        pruned_info = prune_backups(output_dir, keep_last=keep_last, root=root)
        if pruned_info.get("pruned"):
            print(f"  [i] Auto-pruned {len(pruned_info['pruned'])} older backup(s) (retaining last {keep_last}).", flush=True)
    return archive_path


def prune_backups(output_dir: Path = None, keep_last: int = 5, root: Path = None) -> dict:
    """Prune older backups beyond keep_last, removing both the .tar.gz and .json metadata sidecars."""
    if output_dir is None:
        if root is None:
            root = get_project_root()
        output_dir = root / "backups"
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return {"retained": [], "pruned": [], "keep_last": keep_last, "total_on_disk": 0}

    archives = sorted(output_dir.glob("aio-backup-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    retained = []
    pruned = []

    for i, archive in enumerate(archives):
        if i < keep_last:
            retained.append(archive.name)
        else:
            pruned.append(archive.name)
            archive.unlink(missing_ok=True)
            sidecar = archive.with_suffix(archive.suffix + ".json")
            sidecar.unlink(missing_ok=True)

    return {
        "retained": retained,
        "pruned": pruned,
        "keep_last": keep_last,
        "total_on_disk": len(retained)
    }


def get_backup_telemetry(output_dir: Path = None, root: Path = None) -> dict:
    """Get high-level telemetry on backups for the portal and status displays."""
    if output_dir is None:
        if root is None:
            root = get_project_root()
        output_dir = root / "backups"
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return {"count": 0, "total_size_mb": 0.0, "latest": None, "archives": []}

    archives = sorted(output_dir.glob("aio-backup-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    total_bytes = 0
    items = []
    for arch in archives:
        sz = arch.stat().st_size
        total_bytes += sz
        mtime = datetime.fromtimestamp(arch.stat().st_mtime, timezone.utc).isoformat()
        items.append({
            "name": arch.name,
            "size_mb": round(sz / (1024 * 1024), 2),
            "mtime": mtime
        })

    return {
        "count": len(items),
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "latest": items[0] if items else None,
        "archives": items
    }


def latest_backup_status(directory):
    directory=Path(directory)
    archives=sorted(directory.glob('aio-backup-*.tar.gz'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not archives:return {'status':'missing','complete':False}
    archive=archives[0]
    try:
        data=json.loads(archive.with_suffix(archive.suffix+'.json').read_text(encoding='utf-8'))
        if data.get('archive')!=archive.name or data.get('sizeBytes')!=archive.stat().st_size:raise ValueError('Backup changed')
        return {key:data.get(key) for key in ('archive','createdAt','sizeBytes','sha256','postgresIncluded','configurationIncluded','profileIncluded','complete')} | {'status':'complete' if data.get('complete') else 'partial'}
    except (OSError,ValueError):return {'status':'unverified','complete':False,'archive':archive.name}


def restore_file(source, destination):
    source, destination = Path(source), Path(destination)
    with source.open('rb') as handle:
        sqlite = handle.read(16) == b'SQLite format 3\x00'
    if sqlite:
        # Applications must be stopped; a stale journal must never replay over a snapshot.
        for suffix in ('-wal', '-shm', '-journal'):
            destination.with_name(destination.name + suffix).unlink(missing_ok=True)
    return shutil.copy2(source, destination)


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
            members = tar.getmembers()
            for member in members:
                target = (tmp_path / member.name).resolve()
                if (not (member.isfile() or member.isdir())
                        or (target != tmp_path and tmp_path not in target.parents)):
                    print(f"[!] Error: Unsafe archive member: {member.name}", file=sys.stderr)
                    return False
            destination = root.resolve()
            for member in members:
                target = (destination / member.name).resolve()
                if target != destination and destination not in target.parents:
                    print("[!] Error: Restore destination contains an escaping symbolic link.", file=sys.stderr)
                    return False
            root.mkdir(parents=True, exist_ok=True)
            tar.extractall(tmp_path, members=members)

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
            shutil.copytree(data_backup, target_data, dirs_exist_ok=True, copy_function=restore_file)
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
                return False

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
    group.add_argument("--prune", type=int, nargs="?", const=5, metavar="KEEP_N", help="Prune older backups keeping last N (default: 5)")
    group.add_argument("--status", action="store_true", help="Show backup telemetry and retention status")
    parser.add_argument("--keep-last", type=int, default=5, help="Number of backups to keep during auto-prune (default: 5, 0 to disable)")
    parser.add_argument("--include-cache", action="store_true", help="Include heavy proxy scrape caches (e.g. stremthru.db)")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to save the backup")

    args = parser.parse_args()
    root = get_project_root()
    out_dir = Path(args.output_dir) if args.output_dir else root / "backups"

    if args.backup:
        print(f"[i] Backing up AIO Local Stack from {root}...", flush=True)
        archive = create_backup(out_dir, root, include_cache=args.include_cache, keep_last=args.keep_last)
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

    elif args.prune is not None:
        keep = int(args.prune)
        print(f"[i] Pruning backups in {out_dir} (retaining last {keep})...", flush=True)
        result = prune_backups(out_dir, keep_last=keep, root=root)
        print(f"[✓] Prune completed. {len(result['retained'])} retained, {len(result['pruned'])} deleted.", flush=True)
        for p in result['pruned']:
            print(f"    - Deleted: {p}")

    elif args.status:
        telemetry = get_backup_telemetry(out_dir, root)
        print("\nAIO Stack Backup Telemetry:")
        print("-" * 55)
        print(f"  Total Backups on Disk : {telemetry['count']}")
        print(f"  Total Backup Footprint: {telemetry['total_size_mb']:.2f} MB")
        if telemetry['latest']:
            print(f"  Latest Archive        : {telemetry['latest']['name']} ({telemetry['latest']['size_mb']} MB)")
        print("-" * 55)


if __name__ == "__main__":
    main()
