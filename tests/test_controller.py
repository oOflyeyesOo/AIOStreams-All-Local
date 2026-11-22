import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('controller', Path(__file__).resolve().parents[1] / 'docker/controller/controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class ControllerTests(unittest.TestCase):
    def test_rewrite_only_host_sources(self):
        config = {'services': {'controller': {'volumes': [
            {'type': 'bind', 'source': '/workspace', 'target': '/workspace'},
            {'type': 'volume', 'source': 'control-socket', 'target': '/runtime'}],
            'environment': {'PATH_VALUE': '/workspace/private'}, 'build': {'context': '/workspace'}},
            'app': {'volumes': [{'type': 'bind', 'source': '/workspace/data/app', 'target': '/data'}]}}}
        result = controller.rewrite_mount_paths(config, '/srv/my stack')
        self.assertEqual(result['services']['app']['volumes'][0]['source'], '/srv/my stack/data/app')
        self.assertEqual(result['services']['controller']['volumes'][0]['target'], '/workspace')
        self.assertEqual(result['services']['controller']['environment']['PATH_VALUE'], '/workspace/private')
        self.assertEqual(result['services']['controller']['volumes'][1]['source'], 'control-socket')

    def test_windows_mount_path(self):
        self.assertEqual(controller.daemon_host_path(r'C:\Users\example\My Project'),
                         '/run/desktop/mnt/host/c/Users/example/My Project')

    def test_linux_mount_path(self):
        self.assertEqual(controller.daemon_host_path('/srv/my project'), '/srv/my project')

    def test_identity_requires_compose_and_project_mount(self):
        with self.assertRaises(RuntimeError):
            controller.project_identity({'Config': {'Labels': {}}, 'Mounts': []})

    def test_identity_comes_from_own_compose_labels(self):
        data = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
                'Mounts': [{'Destination': '/workspace', 'Source': '/srv/aio'}]}
        self.assertEqual(controller.project_identity(data), ('aio-test', '/srv/aio'))

    def test_apply_never_traverses_controller_dependency(self):
        own = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
               'Mounts': [{'Destination': '/workspace', 'Source': '/srv/aio'}]}
        config = {'services': {'controller': {'restart': 'unless-stopped'},
                              'portal': {'restart': 'unless-stopped', 'depends_on': {'controller': {}}},
                              'shared-postgres': {'restart': 'unless-stopped'},
                              'init-postgres': {'restart': 'no'}, 'init-configs': {'restart': 'no'},
                              'stack-bootstrap': {'restart': 'no'}}}
        with patch.dict(controller.os.environ, {'HOSTNAME': 'test'}), patch.object(controller, 'command_json', side_effect=[[own], config]), patch.object(controller, 'log_command') as command:
            controller.apply()
        for call in command.call_args_list:
            arguments = call.args[0]
            if 'up' in arguments:
                self.assertIn('--no-deps', arguments)
                self.assertNotIn('controller', arguments[arguments.index('--wait-timeout') + 1 + 1:])
        self.assertEqual(controller.JOB['status'], 'complete')

    def test_subsense_health_failure_does_not_block_bootstrap(self):
        own = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
               'Mounts': [{'Destination': '/workspace', 'Source': '/srv/aio'}]}
        config = {'services': {'aiostreams': {}, 'subsense': {}, 'stack-bootstrap': {}}}
        steps = []

        def command(args, step, **kwargs):
            steps.append(args)
            if args[-1] == 'subsense':
                raise RuntimeError('SubSense is unhealthy')

        with patch.dict(controller.os.environ, {'HOSTNAME': 'test'}), \
             patch.object(controller, 'command_json', side_effect=[[own], config]), \
             patch.object(controller, 'log_command', side_effect=command):
            controller.apply()

        self.assertEqual([args[-1] for args in steps], ['aiostreams', 'subsense', 'stack-bootstrap'])
        self.assertEqual(controller.JOB['status'], 'complete')
        self.assertIn('SubSense is unhealthy', controller.JOB['logs'][-1])

    def test_refreshes_only_aiostreams_when_bootstrap_changes_player_alias(self):
        own = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
               'Mounts': [{'Destination': '/workspace', 'Source': '/srv/aio'}]}
        config = {'services': {'aiostreams': {'environment': {'ALIASED_CONFIGURATIONS': 'local:id:before'}},
                              'prowlarr': {}, 'stack-bootstrap': {'restart': 'no'}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / '.env'
            env.write_text('ALIASED_CONFIGURATIONS=local:id:before\n')

            def command(args, step, **kwargs):
                if args[-1] == 'stack-bootstrap':
                    env.write_text('ALIASED_CONFIGURATIONS=local:id:after\n')
                if step == 'Refreshing AIOStreams player links':
                    self.assertEqual(args[args.index('--wait-timeout') + 2:], ['aiostreams'])
                    updated = json.loads(Path(args[args.index('-f') + 1]).read_text())
                    self.assertEqual(updated['services']['aiostreams']['environment']['ALIASED_CONFIGURATIONS'],
                                     'local:id:after')

            with patch.object(controller, 'ROOT', root), patch.dict(controller.os.environ, {'HOSTNAME': 'test'}), \
                 patch.object(controller, 'command_json', side_effect=[[own], config]), \
                 patch.object(controller, 'log_command', side_effect=command) as logged:
                controller.apply()

        self.assertEqual(logged.call_args.args[1], 'Refreshing AIOStreams player links')
        self.assertEqual(controller.JOB['status'], 'complete')

    def test_controller_parses_and_normalizes_legacy_profiles(self):
        own = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
               'Mounts': [{'Destination': '/workspace', 'Source': '/srv/aio'}]}
        config = {'services': {
            'prowlarr': {'profiles': ['core', 'scrapers', 'all']},
            'zilean': {'profiles': ['core', 'scrapers', 'all']},
            'bitmagnet': {'profiles': ['core', 'scrapers', 'all']},
            'flaresolverr': {'profiles': ['core', 'scrapers', 'all']},
            'stremthru': {'profiles': ['core', 'scrapers', 'all']},
            'aiometadata': {'profiles': ['core', 'scrapers', 'all']},
            'postersplus': {'profiles': ['core', 'scrapers', 'all']},
            'lumiere-db': {'profiles': ['core', 'scrapers', 'all']},
            'anime-kitsu': {'profiles': ['anime', 'anime-db', 'scrapers', 'all']},
            'jikan-api': {'profiles': ['anime', 'anime-db', 'all']},
        }}
        started = []
        def command(args, step, **kwargs):
            if 'up' in args:
                started.extend(args[args.index('--wait-timeout') + 2:])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('COMPOSE_PROFILES="scrapers" # legacy comment\n')
            with patch.object(controller, 'ROOT', root), patch.dict(controller.os.environ, {'HOSTNAME': 'test'}), \
                 patch.object(controller, 'command_json', side_effect=[[own], config]), \
                 patch.object(controller, 'log_command', side_effect=command):
                controller.apply()

        for svc in ['prowlarr', 'zilean', 'bitmagnet', 'flaresolverr', 'stremthru', 'aiometadata', 'postersplus', 'lumiere-db', 'anime-kitsu']:
            self.assertIn(svc, started)
        self.assertNotIn('jikan-api', started)
