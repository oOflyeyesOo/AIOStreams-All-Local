import unittest
from unittest.mock import patch, MagicMock
from tests.test_portal import portal


class WebhookSecurityTests(unittest.TestCase):
    def test_only_discord_webhook_endpoints_are_allowed(self):
        for host in ('discord.com', 'discordapp.com'):
            for prefix in ('/api', '/api/v10'):
                self.assertTrue(portal.is_safe_webhook_url(
                    f'https://{host}{prefix}/webhooks/123/fixture_token-abc')[0])
        for url in (
            'https://private.example/api/webhooks/123/token',
            'https://discord.com.evil.example/api/webhooks/123/token',
            'https://127.0.0.1/api/webhooks/123/token',
            'https://[::1]/api/webhooks/123/token',
            'https://discord.com:444/api/webhooks/123/token',
            'https://user:pass@discord.com/api/webhooks/123/token',
            'http://discord.com/api/webhooks/123/token',
            'https://discord.com/api/webhooks/123/token#fragment',
            'https://discord.com/api/webhooks/123/../token',
            'https://discord.com/api/webhooks/123/token\n',
            'https://discord.com:invalid/api/webhooks/123/token',
            'https://[bad', None, 123,
        ):
            with self.subTest(url=url):
                with patch.object(portal.urllib.request, 'build_opener') as opener:
                    self.assertFalse(portal.dispatch_webhook_notification(url, 'test', 'test')[0])
                    opener.assert_not_called()

    def test_delivery_disables_redirects_and_masks_exception_secrets(self):
        url = 'https://discord.com/api/webhooks/123/fixture-secret'
        opener = MagicMock()
        opener.open.side_effect = OSError(url)
        with patch.object(portal.urllib.request, 'build_opener', return_value=opener) as build:
            ok, detail = portal.dispatch_webhook_notification(url, 'test', 'test')
        self.assertFalse(ok)
        self.assertNotIn('fixture-secret', detail)
        handler = build.call_args.args[0]
        self.assertIsInstance(handler, portal.NoRedirectHandler)
        for target in ('https://127.0.0.1/', 'https://discord.com/api/webhooks/456/other'):
            self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, target))

    def test_successful_delivery_preserves_discord_payload(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 204
        with patch.object(portal.urllib.request, 'build_opener', return_value=opener):
            ok, detail = portal.dispatch_webhook_notification(
                'https://discord.com/api/webhooks/123/fixture', 'Title', 'Message')
        self.assertTrue(ok)
        self.assertIn('204', detail)
        self.assertIn(b'Message', opener.open.call_args.args[0].data)
