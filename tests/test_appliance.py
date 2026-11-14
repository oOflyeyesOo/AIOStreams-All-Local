import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from tools.usenet_config import credential

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_env', ROOT / 'docker/all-in-one/prepare_env.py')
prepare_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_env)


class ApplianceTests(unittest.TestCase):
    def test_environment_persists_and_encodes_nntp_password(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'data'
            root.mkdir()
            try:
                (root / 'probe').symlink_to(root / 'missing')
                (root / 'probe').unlink()
            except OSError:
                self.skipTest('Symlink creation requires OS permission')
            (root / '.env.example').write_text('COMPOSE_PROFILES=scrapers\nUSENET_ENABLED=false\nUSENET_HOST=\nUSENET_USER=\nUSENET_PASS=\nPREMIUMIZE_API_KEY=\n')
            (root / '.env').write_text('PREMIUMIZE_API_KEY=fixture-saved\n')
            password = "fixture$pass'\""
            prepare_env.prepare(root, data, {'COMPOSE_PROFILES': 'core', 'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture', 'USENET_USER': 'fixture-user', 'USENET_PASS': password})
            self.assertTrue((root / '.env').is_symlink())
            text = (data / '.env').read_text()
            self.assertNotIn(password, text)
            values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
            self.assertEqual(credential(values, 'USENET_PASS'), password)
            self.assertEqual(values['COMPOSE_PROFILES'], 'core')
            self.assertEqual(values['PREMIUMIZE_API_KEY'], 'fixture-saved')
            prepare_env.prepare(root, data, {})
            self.assertEqual((data / '.env').read_text(), text)

    def test_entrypoint_uses_networked_portal_and_single_controller_setup(self):
        script = (ROOT / 'docker/all-in-one/entrypoint.sh').read_text()
        self.assertNotIn('--scale portal=0', script)
        self.assertNotIn('python3 -u /app/init/bootstrap/setup_stack.py', script)
        self.assertIn('--scale stack-bootstrap=0', script)
        self.assertIn('docker compose exec -T portal', script)
        self.assertNotIn('docker rm -f $(docker ps -aq)', script)

    def test_data_mounts_resolve_appliance_links_in_all_setup_containers(self):
        import yaml
        config = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
        for service in ('portal', 'controller', 'stack-bootstrap'):
            self.assertTrue(any(v.startswith('./data:/data') for v in config['services'][service]['volumes']), service)
