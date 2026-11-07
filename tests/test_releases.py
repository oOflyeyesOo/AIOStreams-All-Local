import base64,json,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools import release_manager as releases
from tools.backup import create_backup,latest_backup_status
PIN='ghcr.io/example/service@sha256:'+'1'*64
NEXT='ghcr.io/example/service@sha256:'+'2'*64
class ReleaseTests(unittest.TestCase):
    def lock(self,image=PIN):return {'format':'aio-release-v1','release':'fixture-v1','images':{'portal':image}}
    def test_mutable_tags_and_embedded_registry_credentials_are_rejected(self):
        for ref in ('ghcr.io/example/service:latest','https://secret@host/image@sha256:'+'1'*64,'sha256:'+'1'*64):
            with self.assertRaises(ValueError):releases.validate_lock(self.lock(ref))
    def test_lock_roundtrip_and_image_set_coverage(self):
        lock=self.lock();self.assertEqual(releases.decode_lock(releases.encoded_lock(lock)),lock)
        config={'services':{'portal':{'image':'old:latest'}}}
        self.assertEqual(releases.apply_images(config,lock)['services']['portal']['image'],PIN)
        with self.assertRaises(ValueError):releases.apply_images({'services':{'different':{'image':'old'}}},lock)
    def test_release_preview_is_explicit_about_migrations(self):
        result=releases.preview(self.lock(),self.lock(NEXT))
        self.assertEqual(len(result['changes']),1);self.assertTrue(result['backupRequired']);self.assertIn('not inferred',result['migrations'])
    def test_partial_backup_cannot_be_used_for_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.env').write_text('FIXTURE=1')
            with patch('tools.backup.dump_postgres',return_value=False):archive=create_backup(root=root)
            self.assertEqual(latest_backup_status(root/'backups')['status'],'partial')
            with self.assertRaises((RuntimeError,KeyError)):releases.verify_backup(archive)
    def test_upgrade_does_not_pull_or_restart_after_backup_failure(self):
        import argparse
        with tempfile.TemporaryDirectory() as folder:
            args=argparse.Namespace(current='current',target='target',project='fixture',env_file=None,allow_local=False,backup_dir=folder)
            with patch.object(releases,'check_pinned'),patch.object(releases,'portal_id',return_value='portal-id'),patch.object(releases,'command',side_effect=RuntimeError('backup failed')) as command:
                with self.assertRaises(RuntimeError):releases.upgrade(args)
            self.assertEqual(command.call_count,1)
            self.assertNotIn('pull',command.call_args.args[0])
    def test_legacy_backup_is_not_mislabeled_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'aio-backup-fixture.tar.gz').write_bytes(b'not-verified')
            self.assertEqual(latest_backup_status(root)['status'],'unverified')
    def test_sql_without_saved_profile_is_partial_and_blocks_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.env').write_text('FIXTURE=1')
            def dump(path):path.write_text('SELECT 1;');return True
            with patch('tools.backup.dump_postgres',side_effect=dump):archive=create_backup(root=root)
            self.assertEqual(latest_backup_status(root/'backups')['status'],'partial')
            self.assertFalse(latest_backup_status(root/'backups')['profileIncluded'])
            with self.assertRaises(RuntimeError):releases.verify_backup(archive)
