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
            (root / '.env.example').write_text('COMPOSE_PROFILES=core\nUSENET_ENABLED=false\nUSENET_HOST=\nUSENET_USER=\nUSENET_PASS=\nPREMIUMIZE_API_KEY=\n')
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

    def test_appliance_restart_preserves_portal_profiles_unless_explicitly_overridden(self):
        import yaml
        config = yaml.safe_load((ROOT / 'docker-compose.aio.yml').read_text())
        environment = config['services']['aio-stack']['environment']
        self.assertIn('COMPOSE_PROFILES=${COMPOSE_PROFILES:-}', environment)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'data'
            root.mkdir()
            try:
                (root / 'probe').symlink_to(root / 'missing')
                (root / 'probe').unlink()
            except OSError:
                self.skipTest('Symlink creation requires OS permission')
            # Use the shipped template so fresh-install defaults are covered too.
            (root / '.env.example').write_text((ROOT / '.env.example').read_text())
            default_environment = {'COMPOSE_PROFILES': ''}
            prepare_env.prepare(root, data, default_environment)

            def saved():
                return dict(line.split('=', 1) for line in (data / '.env').read_text().splitlines()
                            if '=' in line and not line.lstrip().startswith('#'))

            self.assertEqual(saved()['COMPOSE_PROFILES'], 'core')
            # Simulate the portal's saved choice before restarting the appliance.
            (data / '.env').write_text('COMPOSE_PROFILES=core,anime,tunnel\nPREMIUMIZE_API_KEY=fixture-only\n')
            prepare_env.prepare(root, data, default_environment)
            self.assertEqual(saved()['COMPOSE_PROFILES'], 'core,anime,tunnel')
            self.assertEqual(saved()['PREMIUMIZE_API_KEY'], 'fixture-only')
            prepare_env.prepare(root, data, {'COMPOSE_PROFILES': 'core'})
            self.assertEqual(saved()['COMPOSE_PROFILES'], 'core')
            self.assertEqual(saved()['PREMIUMIZE_API_KEY'], 'fixture-only')

    def test_prepare_migrates_legacy_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app'
            data = Path(directory) / 'data'
            root.mkdir()
            try:
                (root / 'probe').symlink_to(root / 'missing')
                (root / 'probe').unlink()
            except OSError:
                self.skipTest('Symlink creation requires OS permission')
            (root / '.env.example').write_text('COMPOSE_PROFILES=core\nADDON_PASSWORD=admin\n')
            (root / '.env').write_text('COMPOSE_PROFILES="scrapers,anime-db,tunnel" # legacy comment\n')
            prepare_env.prepare(root, data, {})
            text = (data / '.env').read_text()
            values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
            self.assertEqual(values['COMPOSE_PROFILES'], 'core,anime,tunnel')

            # Legacy single 'scrapers' profile
            (data / '.env').write_text('COMPOSE_PROFILES=scrapers\n')
            prepare_env.prepare(root, data, {})
            values = dict(line.split('=', 1) for line in (data / '.env').read_text().splitlines() if '=' in line)
            self.assertEqual(values['COMPOSE_PROFILES'], 'core')

            # Incoming COMPOSE_PROFILES='scrapers' in environment dict migrates to core
            prepare_env.prepare(root, data, {'COMPOSE_PROFILES': 'scrapers'})
            values = dict(line.split('=', 1) for line in (data / '.env').read_text().splitlines() if '=' in line)
            self.assertEqual(values['COMPOSE_PROFILES'], 'core')

    def test_entrypoint_uses_networked_portal_and_single_controller_setup(self):
        script = (ROOT / 'docker/all-in-one/entrypoint.sh').read_text()
        self.assertNotIn('--scale portal=0', script)
        self.assertNotIn('python3 -u /app/init/bootstrap/setup_stack.py', script)
        self.assertIn("'/^stack-bootstrap$/d'", script)
        self.assertIn("'/^subsense$/d'", script)
        self.assertIn('docker compose exec -T portal', script)
        self.assertNotIn('docker rm -f $(docker ps -aq)', script)
        # Controller and portal start before bulk image pulls/boot contention.
        ctl_idx = script.index('docker compose up -d --no-build --wait --wait-timeout 180 controller')
        portal_idx = script.index('docker compose up -d --no-deps --no-build --wait --wait-timeout 180 portal')
        pull_idx = script.index('docker compose pull --ignore-buildable')
        stack_idx = script.index('docker compose up -d --remove-orphans --no-build --wait --wait-timeout 600 "${startup_services[@]}"')
        self.assertLess(ctl_idx, portal_idx)
        self.assertLess(portal_idx, pull_idx)
        self.assertLess(pull_idx, stack_idx)

    def test_appliance_dockerfile_copies_required_portal_assets(self):
        dockerfile = (ROOT / 'docker/all-in-one/Dockerfile').read_text()
        for entry in (
            'COPY docker-compose.yml /app/docker-compose.yml',
            'COPY .env.example /app/.env.example',
            'COPY index.html /app/index.html',
            'COPY dashboard.html /app/dashboard.html',
            'COPY app.webmanifest /app/app.webmanifest',
            'COPY assets/ /app/assets/',
            'COPY init/ /app/init/',
            'COPY templates/ /app/templates/',
            'COPY tools/ /app/tools/',
            'COPY docker/ /app/docker/',
        ):
            self.assertIn(entry, dockerfile)

    def test_check_appliance_prints_stderr_and_portal_diagnostics(self):
        script = (ROOT / 'tests/check_appliance.py').read_text()
        self.assertIn('proc.stderr', script)
        self.assertIn("'portal', 'controller'", script)

    def test_data_mounts_resolve_appliance_links_in_all_setup_containers(self):
        import yaml
        config = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
        for service in ('portal', 'controller', 'stack-bootstrap'):
            self.assertTrue(any(v.startswith('./data:/data') for v in config['services'][service]['volumes']), service)
