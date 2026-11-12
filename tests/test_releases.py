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
    def test_preview_detects_removed_retired_services(self):
        current = {'format': 'aio-release-v1', 'release': 'v1', 'images': {
            'portal': PIN, 'debrid-search': PIN, 'mediafusion': PIN, 'sootio': PIN
        }}
        target = {'format': 'aio-release-v1', 'release': 'v2', 'images': {
            'portal': NEXT
        }}
        res = releases.preview(current, target)
        self.assertEqual(res['removedServices'], ['debrid-search', 'mediafusion', 'sootio'])
        self.assertEqual(len(res['changes']), 1)
        self.assertEqual(res['changes'][0]['service'], 'portal')
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
    def test_rollback_rejects_project_mismatch_and_checksum_tampering(self):
        import argparse
        with tempfile.TemporaryDirectory() as folder:
            state_file = Path(folder) / "upgrade-state.json"
            archive = Path(folder) / "backup.tar.gz"
            archive.write_bytes(b"dummy")
            state = {
                'format': 'aio-upgrade-v1',
                'project': 'wrong-project',
                'archive': str(archive),
                'backupSha256': 'wrong-sha'
            }
            state_file.write_text(json.dumps(state))
            args = argparse.Namespace(project='my-project', state=str(state_file), allow_local=False, env_file=None)
            with self.assertRaises(ValueError):
                releases.rollback(args)

            state['project'] = 'my-project'
            state_file.write_text(json.dumps(state))
            with patch.object(releases, 'verify_backup', return_value='correct-sha'):
                with self.assertRaises(ValueError):
                    releases.rollback(args)
    def test_rollback_stops_target_services_and_invokes_restore(self):
        import argparse
        with tempfile.TemporaryDirectory() as folder:
            state_file = Path(folder) / "upgrade-state.json"
            archive = Path(folder) / "backup.tar.gz"
            archive.write_bytes(b"dummy")
            target_compose = Path(folder) / "target.yml"
            target_compose.write_text("services:\n  portal:\n    image: " + NEXT + "\n  aiostreams:\n    image: " + NEXT + "\n")
            prev_compose = Path(folder) / "prev.yml"
            prev_compose.write_text("services:\n  portal:\n    image: " + PIN + "\n")
            state = {
                'format': 'aio-upgrade-v1',
                'project': 'my-proj',
                'previous': str(prev_compose),
                'target': str(target_compose),
                'archive': str(archive),
                'archiveName': 'backup.tar.gz',
                'backupSha256': 'valid-sha',
                'restoreImage': 'ghcr.io/example/portal:latest',
                'status': 'complete'
            }
            state_file.write_text(json.dumps(state))
            args = argparse.Namespace(project='my-proj', state=str(state_file), allow_local=True, env_file=None)
            commands = []
            with patch.object(releases, 'verify_backup', return_value='valid-sha'), \
                 patch.object(releases, 'portal_id', return_value='portal-123'), \
                 patch.object(releases, 'command', side_effect=lambda cmd, **kw: commands.append(cmd) or "") as cmd_mock, \
                 patch.object(releases, 'controller') as ctrl_mock:
                releases.rollback(args)
                self.assertTrue(ctrl_mock.called)
                stop_cmds = [c for c in commands if 'stop' in c]
                self.assertTrue(any('aiostreams' in c for c in stop_cmds))
