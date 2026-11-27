import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch
from tests import check_bootstrap_completion as check


CONTAINER = 'a' * 64


def result(output='', code=0):
    return subprocess.CompletedProcess([], code, stdout=output, stderr='fixture-secret')


class BootstrapCompletionTests(unittest.TestCase):
    def test_waits_for_actual_one_shot_exit_not_health(self):
        with patch.object(check.subprocess, 'run', side_effect=[result(CONTAINER + '\n'), result('0\n')]) as run:
            self.assertEqual(check.wait_for_bootstrap('aio-release', 'release.yml', 'fixture.env', 45), CONTAINER)
        self.assertEqual(run.call_args_list[0].args[0], ['docker', 'compose', '-p', 'aio-release',
            '--env-file', 'fixture.env', '-f', 'release.yml', 'ps', '--all', '--quiet', 'stack-bootstrap'])
        self.assertEqual(run.call_args_list[1].args[0], ['docker', 'wait', CONTAINER])
        self.assertEqual(run.call_args_list[1].kwargs['timeout'], 45)

    def test_missing_or_ambiguous_container_never_starts_wait(self):
        for first in (result(''), result(CONTAINER + '\n' + CONTAINER), result('not-a-container'), result(CONTAINER, 1)):
            with self.subTest(first=first.stdout):
                with patch.object(check.subprocess, 'run', return_value=first) as run:
                    with self.assertRaises(check.BootstrapCompletionError):
                        check.wait_for_bootstrap('aio-release', 'release.yml', 'fixture.env')
                    self.assertEqual(run.call_count, 1)

    def test_failure_invalid_output_and_timeout_do_not_pass(self):
        for ending in (result('1\n'), result('137\n'), result('0\n', 1), result(''),
                       result('0\n1\n'), subprocess.TimeoutExpired(['docker', 'wait'], 2), OSError('fixture-secret')):
            with self.subTest(ending=type(ending).__name__):
                with patch.object(check.subprocess, 'run', side_effect=[result(CONTAINER), ending]):
                    with self.assertRaises(check.BootstrapCompletionError) as error:
                        check.wait_for_bootstrap('aio-release', 'release.yml', 'fixture.env')
                    self.assertNotIn('fixture-secret', str(error.exception))

    def test_nonfixture_project_or_invalid_deadline_is_rejected_before_docker(self):
        with patch.object(check.subprocess, 'run') as run:
            for project, timeout in (('production', 30), ('aio-release', 0), ('aio-release', 1801)):
                with self.assertRaises(check.BootstrapCompletionError):
                    check.wait_for_bootstrap(project, 'release.yml', 'fixture.env', timeout)
            run.assert_not_called()

    def test_cli_returns_failure_without_leaking_command_output(self):
        with patch.object(check.subprocess, 'run', side_effect=[result(CONTAINER), result('7')]), contextlib.redirect_stderr(io.StringIO()) as err:
            code = check.main(['--project', 'aio-release', '--compose', 'release.yml', '--env-file', 'fixture.env'])
        self.assertEqual(code, 1)
        self.assertIn('exit code 7', err.getvalue())
        self.assertNotIn('fixture-secret', err.getvalue())
