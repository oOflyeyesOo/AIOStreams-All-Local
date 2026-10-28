import importlib.util
from pathlib import Path
import unittest
import tempfile
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
                service_offset = arguments.index('--wait-timeout') + 2
                self.assertNotIn('controller', arguments[service_offset:])
        self.assertEqual(controller.JOB['status'], 'complete')

    def test_manager_apply_preserves_manager_owned_portal(self):
        own = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
               'Mounts': [{'Destination': '/workspace', 'Source': '/var/lib/docker/volumes/aio-test_aio-config/_data'}]}
        config = {'services': {'controller': {'restart': 'unless-stopped'},
                              'portal': {'restart': 'unless-stopped'},
                              'aiostreams': {'restart': 'unless-stopped'},
                              'stack-bootstrap': {'restart': 'no'}}}
        with patch.dict(controller.os.environ, {'HOSTNAME': 'test'}), patch.object(controller, 'COMPOSE_FILE', 'compose.manager.yml'), patch.object(controller, 'command_json', side_effect=[[own], config]) as render, patch.object(controller, 'log_command') as command:
            controller.apply()
        self.assertIn('/workspace/compose.manager.yml', render.call_args_list[1].args[0])
        up = command.call_args_list[0].args[0]
        self.assertIn('aiostreams', up)
        self.assertNotIn('portal', up)
        self.assertNotIn('controller', up)
        self.assertEqual(controller.JOB['status'], 'complete')

    def test_apply_includes_selected_profile_services_only(self):
        own = {'Config': {'Labels': {'com.docker.compose.project': 'aio-test'}},
               'Mounts': [{'Destination': '/workspace', 'Source': '/srv/aio'}]}
        config = {'services': {'comet': {'profiles': ['core', 'all']},
                               'sootio': {'profiles': ['scrapers', 'all']},
                               'stack-check': {'profiles': ['test']}}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env').write_text('COMPOSE_PROFILES=core\n')
            with patch.object(controller, 'ROOT', root), patch.dict(controller.os.environ, {'HOSTNAME': 'test'}), patch.object(controller, 'command_json', side_effect=[[own], config]), patch.object(controller, 'log_command') as command:
                controller.apply()
            up = command.call_args_list[0].args[0]
            self.assertIn('comet', up)
            self.assertNotIn('sootio', up)
            self.assertNotIn('stack-check', up)
            self.assertEqual(controller.JOB['status'], 'complete')
