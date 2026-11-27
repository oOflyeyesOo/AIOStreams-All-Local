import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_portal import portal


class PlayerInstallPathTests(unittest.TestCase):
    def test_player_uses_standard_profile_without_legacy_files_or_env_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'data/aiostreams/aiostreams_install.json'
            profile.parent.mkdir(parents=True)
            handler = object.__new__(portal.AppliancePortalHandler)
            for spelling in ('encrypted_password', 'encryptedPassword'):
                profile.write_text(json.dumps({'uuid': 'fixture-id', spelling: 'fixture-token'}))
                with patch.object(portal, 'WEB_ROOT', str(root)), patch.object(portal, 'read_saved_env', return_value={}):
                    self.assertEqual(handler._get_jellyfin_credentials(), ('fixture-id', 'fixture-token'))
