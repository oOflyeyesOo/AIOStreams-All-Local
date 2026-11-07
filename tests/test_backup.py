import sqlite3
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
