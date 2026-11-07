import sqlite3
from concurrent.futures import ThreadPoolExecutor
import tarfile
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import backup


class BackupTests(unittest.TestCase):
    def test_backup_restore_round_trip_without_postgres(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "source"
            output = root / "backups"
            (root / "data" / "aiostreams").mkdir(parents=True)
            (root / ".env").write_text("ADDON_PASSWORD=test-only\n", encoding="utf-8")
            (root / "data" / "aiostreams" / "db.sqlite").write_bytes(b"sqlite-fixture")

            with patch.object(backup, "dump_postgres", return_value=False):
                archive = backup.create_backup(output_dir=output, root=root)

            restored = Path(temp_dir) / "restored"
            restored.mkdir()
            self.assertTrue(backup.restore_backup(archive, root=restored))
            self.assertEqual(
                (restored / ".env").read_text(encoding="utf-8"),
                "ADDON_PASSWORD=test-only\n",
            )
            self.assertEqual(
                (restored / "data" / "aiostreams" / "db.sqlite").read_bytes(),
                b"sqlite-fixture",
            )

    def test_simultaneous_backups_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(backup,'dump_postgres',return_value=False), ThreadPoolExecutor(max_workers=2) as pool:
                archives=list(pool.map(lambda _:backup.create_backup(root=root),range(2)))
            self.assertNotEqual(*archives)
            for archive in archives:
                with tarfile.open(archive) as tar:
                    self.assertIn('backup-manifest.json',tar.getnames())
            self.assertEqual(list((root/'backups').glob('*.tmp')),[])

    def test_backup_keeps_prowlarr_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'data/prowlarr').mkdir(parents=True)
            (root/'data/prowlarr/prowlarr.db').write_bytes(b'indexer configuration')
            with patch.object(backup, 'dump_postgres', return_value=False):
                archive = backup.create_backup(root=root)
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.extractfile('data/prowlarr/prowlarr.db').read(), b'indexer configuration')

    def test_failed_database_restore_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dump = root/'postgres_cluster.sql'
            dump.write_text('INVALID SQL;')
            archive = root/'fixture.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                tar.add(dump,arcname=dump.name)
            with patch.object(backup,'restore_postgres',return_value=False):
                self.assertFalse(backup.restore_backup(archive,root/'restored'))

    def test_existing_destination_symlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source=root/'source';source.mkdir()
            (source/'secret').write_text('preserve')
            target=root/'target';target.mkdir()
            (target/'data').symlink_to(source,target_is_directory=True)
            fixture=root/'fixture';fixture.mkdir()
            (fixture/'secret').write_text('overwrite')
            archive=root/'fixture.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:tar.add(fixture,arcname='data')
            self.assertFalse(backup.restore_backup(archive,target))
            self.assertEqual((source/'secret').read_text(),'preserve')

    def test_offline_restore_removes_stale_sqlite_journals(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'snapshot.db';target=root/'restored.db'
            with sqlite3.connect(source) as db:db.execute('CREATE TABLE sentinel(value text)')
            for suffix in ('-wal','-shm','-journal'):target.with_name(target.name+suffix).write_bytes(b'stale')
            backup.restore_file(source,target)
            for suffix in ('-wal','-shm','-journal'):self.assertFalse(target.with_name(target.name+suffix).exists())
            with sqlite3.connect(target) as db:self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')

    def test_sqlite_snapshot_includes_live_wal_transaction(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "live.sqlite"
            target = Path(folder) / "snapshot.sqlite"
            with sqlite3.connect(source) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE saved(value TEXT)")
                db.execute("INSERT INTO saved VALUES ('committed')")
                db.commit()
                backup.copy_consistent(source, target)
                with sqlite3.connect(target) as restored:
                    self.assertEqual(restored.execute("SELECT value FROM saved").fetchone()[0], "committed")

    def test_restore_rejects_links_and_special_files(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir) / "root"
                root.mkdir()
                archive = Path(temp_dir) / "unsafe.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    member = tarfile.TarInfo("data/escape")
                    member.type = kind
                    member.linkname = "../../outside"
                    tar.addfile(member)
                self.assertFalse(backup.restore_backup(archive, root=root))
                self.assertEqual(list(root.iterdir()), [])

    def test_restore_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "root"
            root.mkdir()
            archive = Path(temp_dir) / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                member = tarfile.TarInfo("../outside.txt")
                member.size = 0
                tar.addfile(member)

            self.assertFalse(backup.restore_backup(archive, root=root))
            self.assertFalse((Path(temp_dir) / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
