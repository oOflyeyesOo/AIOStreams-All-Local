import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('playback_check', Path(__file__).with_name('check_playback.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class PlaybackCheckTests(unittest.TestCase):
    def response(self, data, status=200):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = data
        response.status = status
        return response

    def test_import_does_not_read_profile_or_make_requests(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('profile read')), patch.object(check.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            spec.loader.exec_module(importlib.util.module_from_spec(spec))

    def test_success_is_bounded_media_read_not_decode(self):
        streams = self.response(json.dumps({'streams': [{'url': 'https://example.invalid/signed-secret', 'description': 'AVC', 'behaviorHints': {'videoSize': None}}]}).encode())
        media = self.response(b'\x00\x00\x00\x20ftyp' + b'0' * 1016, 206)
        with patch.object(check.urllib.request, 'urlopen', side_effect=[streams, media]) as request:
            result = check.probe({'uuid': 'fixture', 'encrypted_password': 'fixture'})
        self.assertEqual(result, {'status': 206, 'bytes': 1024})
        media.read.assert_called_once_with(1024)
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=0-1023')

    def test_html_empty_and_short_ranges_fail(self):
        for data in (b'', b'<html>' + b'x' * 1100, b'ftyp'):
            with self.subTest(size=len(data)):
                streams = self.response(json.dumps({'streams': [{'url': 'https://example.invalid/private', 'description': 'AVC'}]}).encode())
                with patch.object(check.urllib.request, 'urlopen', side_effect=[streams, self.response(data)]):
                    with self.assertRaises(ValueError):
                        check.probe({'uuid': 'fixture', 'encryptedPassword': 'fixture'})

    def test_failures_return_nonzero_without_secret_details(self):
        for failure in (OSError('https://host/private-token'), ValueError('provider-secret')):
            output = io.StringIO()
            with patch.object(check, 'INSTALL_INFO') as path, patch.object(check, 'probe', side_effect=failure), contextlib.redirect_stdout(output):
                path.read_text.return_value = '{}'
                self.assertEqual(check.main(), 1)
            self.assertNotIn('private-token', output.getvalue())
            self.assertNotIn('provider-secret', output.getvalue())

    def test_success_message_does_not_claim_browser_playback(self):
        output = io.StringIO()
        with patch.object(check, 'INSTALL_INFO') as path, patch.object(check, 'probe', return_value={'status': 206, 'bytes': 1024}), contextlib.redirect_stdout(output):
            path.read_text.return_value = '{}'
            self.assertEqual(check.main(), 0)
        self.assertIn('Browser decoding not verified', output.getvalue())

    def test_missing_profile_and_missing_candidates_fail(self):
        with patch.object(check.urllib.request, 'urlopen') as request:
            with self.assertRaises(ValueError):
                check.probe({'uuid': 'fixture'})
            request.assert_not_called()
        with patch.object(check.urllib.request, 'urlopen', return_value=self.response(b'{"streams":[]}')):
            with self.assertRaises(ValueError):
                check.probe({'uuid': 'fixture', 'encrypted_password': 'fixture'})
