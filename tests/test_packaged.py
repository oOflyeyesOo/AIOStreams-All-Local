import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

from scripts.generate_manager_compose import generate

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('packaged_entrypoint', ROOT / 'docker/packaged/portal_entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


class PackagedPortalTests(unittest.TestCase):
    def test_bitmagnet_is_decommissioned_from_compose(self):
        for filename in ('docker-compose.yml', 'compose.manager.yml'):
            config = yaml.safe_load((ROOT / filename).read_text(encoding='utf-8'))
            self.assertNotIn('bitmagnet', config['services'])

    def test_manager_profiles_match_source_and_keep_anime_optional(self):
        source = yaml.safe_load((ROOT / 'docker-compose.yml').read_text(encoding='utf-8'))
        manager = generate(yaml.safe_load((ROOT / 'docker-compose.yml').read_text(encoding='utf-8')))

        def selected(config, profiles):
            return {name for name, service in config['services'].items()
                    if not service.get('profiles') or set(service['profiles']).intersection(profiles)}

        for profiles in ({'core'}, {'core', 'anime'}, {'scrapers'}, {'core', 'anime-db'}, {'all'}):
            with self.subTest(profiles=profiles):
                self.assertEqual(selected(manager, profiles), selected(source, profiles))
                active = selected(manager, profiles)
                for name in active:
                    for dependency in manager['services'][name].get('depends_on', {}):
                        self.assertIn(dependency, active, f'{name} requires inactive {dependency}')
        default = selected(manager, set())
        self.assertEqual(default, selected(source, {'core'}))
        self.assertNotIn('jikan-api', default)
        self.assertNotIn('jikan-mongo', default)
        self.assertNotIn('anime-kitsu', default)
        self.assertIn('COMPOSE_PROFILES=${COMPOSE_PROFILES:-}', manager['services']['portal']['environment'])

    def test_profile_selection_survives_reseed_and_accepts_manager_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'image'
            source.mkdir()
            target = root / 'config'
            entrypoint.seed(source, target, {})
            self.assertIn('COMPOSE_PROFILES=core\n', (target / '.env').read_text())
            (target / '.env').write_text('COMPOSE_PROFILES=core,anime\n')
            entrypoint.seed(source, target, {'COMPOSE_PROFILES': ''})
            self.assertIn('COMPOSE_PROFILES=core,anime\n', (target / '.env').read_text())
            entrypoint.seed(source, target, {'COMPOSE_PROFILES': 'core'})
            self.assertIn('COMPOSE_PROFILES=core\n', (target / '.env').read_text())

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

    def test_manager_ports_survive_reseed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source'
            source.mkdir()
            entrypoint.seed(source,root/'target',{'PORT_PROWLARR':'29696','PORT_AIOMETADATA':'24005'})
            env=(root/'target'/'.env').read_text()
            self.assertIn('PORT_PROWLARR=29696',env)
            self.assertIn('PORT_AIOMETADATA=24005',env)

    def test_stack_check_respects_optional_anime_profile(self):
        from tests import check_stack
        self.assertNotIn('anime-kitsu', check_stack.active_checks({'core'}))
        self.assertIn('anime-kitsu', check_stack.active_checks({'core', 'anime'}))
        self.assertIn('anime-kitsu', check_stack.active_checks({'all'}))
