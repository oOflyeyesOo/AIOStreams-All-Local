import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('packaged_entrypoint', ROOT / 'docker/packaged/portal_entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


class PackagedPortalTests(unittest.TestCase):
    def test_first_install_and_upgrade_keep_provider_keys_and_data(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'image'
            source.mkdir()
            (source / 'index.html').write_text('first UI')
            (source / 'compose.manager.yml').write_text('services: {}')
            destination = Path(folder) / 'config'
            entrypoint.seed(source, destination, {'ADDON_PASSWORD': 'test-password', 'AIO_IMAGE_TAG': 'revision-one'})
            with (destination / '.env').open('a') as output:
                output.write('TMDB_API_KEY=keep-this-test-value\nSECRET_KEY=keep-encryption-identity\n')
            (destination / 'data').mkdir()
            (destination / 'data' / 'existing').write_text('keep me')
            (source / 'index.html').write_text('updated UI')
            entrypoint.seed(source, destination, {'ADDON_PASSWORD': 'replacement-password', 'AIO_IMAGE_TAG': 'revision-two'})
            env = (destination / '.env').read_text()
            self.assertIn('TMDB_API_KEY=keep-this-test-value', env)
            self.assertIn('SECRET_KEY=keep-encryption-identity', env)
            self.assertIn('ADDON_PASSWORD=replacement-password', env)
            self.assertIn('AIO_IMAGE_TAG=revision-two', env)
            self.assertNotIn('revision-one', env)
            self.assertEqual((destination / 'index.html').read_text(), 'updated UI')
            self.assertEqual((destination / 'data' / 'existing').read_text(), 'keep me')

    def test_manager_setting_cannot_inject_dotenv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            for value in ('password\nEVIL=true', '${INJECT}', "a'b", 'a#b'):
                with self.assertRaises(ValueError):
                    entrypoint.seed(source, root / 'target', {'ADDON_PASSWORD': value})
