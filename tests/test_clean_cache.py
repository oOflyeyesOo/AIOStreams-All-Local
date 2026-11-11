#!/usr/bin/env python3
"""
Unit tests for tools/clean_cache.py
"""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.clean_cache import clean_stack_cache, get_dir_size


class TestCleanCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="aio-test-clean-cache-"))

        # Setup mock directory structures
        self.hashlists = self.temp_dir / "data" / "stremthru" / "hashlists"
        self.imdb = self.temp_dir / "data" / "stremthru" / "imdb"
        self.cache = self.temp_dir / "data" / "stremthru" / "cache"
        self.posters = self.temp_dir / "data" / "postersplus"
        self.pycache = self.temp_dir / "subdir" / "__pycache__"

        for p in (self.hashlists, self.imdb, self.cache, self.posters, self.pycache):
            p.mkdir(parents=True, exist_ok=True)

        # Create dummy dummy files
        (self.hashlists / "test1.torrent").write_bytes(b"x" * 1024)
        (self.hashlists / "test2.torrent").write_bytes(b"y" * 2048)
        (self.imdb / "title.basics.tsv").write_bytes(b"z" * 4096)
        (self.cache / "temp.cache").write_bytes(b"c" * 512)
        (self.posters / "poster.jpg").write_bytes(b"p" * 8192)
        (self.pycache / "module.cpython-311.pyc").write_bytes(b"b" * 256)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_deletion_failure_does_not_report_success(self):
        with patch('pathlib.Path.unlink',side_effect=PermissionError('fixture read-only')):
            result=clean_stack_cache(self.temp_dir,include_poster_cache=True)
        self.assertFalse(result['success'])
        self.assertTrue(result['errors'])
        self.assertTrue((self.posters/'poster.jpg').exists())

    def test_poster_cleanup_preserves_database_and_configuration(self):
        (self.posters/'cache.db').write_bytes(b'database')
        (self.posters/'settings.json').write_text('{}')
        clean_stack_cache(self.temp_dir,include_poster_cache=True)
        self.assertTrue((self.posters/'cache.db').exists())
        self.assertTrue((self.posters/'settings.json').exists())
        self.assertFalse((self.posters/'poster.jpg').exists())

    def test_symlink_cache_cannot_delete_outside_workspace(self):
        with tempfile.TemporaryDirectory() as outside:
            sentinel=Path(outside)/'preserve.txt';sentinel.write_text('preserve')
            shutil.rmtree(self.hashlists)
            try:
                self.hashlists.symlink_to(outside,target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks not permitted in this environment")
            result=clean_stack_cache(self.temp_dir)
            self.assertFalse(result['success'])
            self.assertEqual(sentinel.read_text(),'preserve')

    def test_get_dir_size(self):
        size = get_dir_size(self.hashlists)
        self.assertEqual(size, 1024 + 2048)

    def test_clean_dry_run(self):
        res = clean_stack_cache(repo_root=self.temp_dir, dry_run=True)
        self.assertTrue(res["success"])
        self.assertTrue(res["dry_run"])
        self.assertGreater(res["total_bytes"], 0)
        # Verify files were NOT deleted
        self.assertTrue((self.hashlists / "test1.torrent").exists())
        self.assertTrue((self.imdb / "title.basics.tsv").exists())

    def test_clean_execute(self):
        res = clean_stack_cache(repo_root=self.temp_dir, include_poster_cache=True, dry_run=False)
        self.assertTrue(res["success"])
        self.assertFalse(res["dry_run"])
        self.assertGreater(res["freed_mb"], 0.0)
        # Verify files WERE deleted
        self.assertFalse((self.hashlists / "test1.torrent").exists())
        self.assertFalse((self.imdb / "title.basics.tsv").exists())
        self.assertFalse((self.posters / "poster.jpg").exists())
        self.assertFalse((self.pycache / "module.cpython-311.pyc").exists())


if __name__ == "__main__":
    unittest.main()
