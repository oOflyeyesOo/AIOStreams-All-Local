import base64,json,unittest
from tools.usenet_config import form_updates,provider_config,public_settings,apply_to_compose

class UsenetConfigTests(unittest.TestCase):
    def settings(self):
        return form_updates({'USENET_ENABLED':'true','USENET_HOST':'news.fixture.invalid','USENET_USER':'fixture-user',
                             'USENET_PASS':'fixture$pass\'"','USENET_PORT':'563','USENET_SSL':'true','USENET_CONNECTIONS':'10'}, {})
    def test_special_credentials_are_preserved_without_plaintext_dotenv_values(self):
        values=self.settings();self.assertEqual(values['USENET_PASS'],'')
        self.assertEqual(base64.b64decode(values['USENET_PASS_B64']).decode(),'fixture$pass\'"')
        provider=provider_config(values)['Providers'][0]
        self.assertEqual(provider['Type'],1);self.assertEqual(provider['Pass'],'fixture$pass\'"');self.assertTrue(provider['UseSsl'])
        public=public_settings(values)
        self.assertTrue(public['USENET_PASSWORD_SAVED']);self.assertNotIn('fixture$pass',json.dumps(public))
        self.assertNotIn(values['USENET_PASS_B64'],json.dumps(public))
    def test_controller_configuration_escapes_only_the_compose_interpolation_layer(self):
        values=self.settings();config={'services':{'infinidysk':{'environment':{}}}}
        compiled=apply_to_compose(config,values)['services']['infinidysk']['environment']['NZBDAV_CONFIG__USENET__PROVIDERS']
        self.assertEqual(json.loads(compiled)['Providers'][0]['Pass'],'fixture$$pass\'"')
    def test_disabling_managed_usenet_keeps_credentials_but_stops_provider_connections(self):
        values=self.settings();values.update(form_updates({'USENET_ENABLED':'false'},values))
        self.assertTrue(public_settings(values)['USENET_PASSWORD_SAVED'])
        self.assertEqual(provider_config(values),{'Providers':[]})
        config=apply_to_compose({'services':{'infinidysk':{'environment':{}}}},values)
        self.assertEqual(json.loads(config['services']['infinidysk']['environment']['NZBDAV_CONFIG__USENET__PROVIDERS']),{'Providers':[]})
    def test_unmanaged_installation_is_not_overwritten_by_blank_form(self):
        values=form_updates({'USENET_ENABLED':'false','USENET_HOST':'','USENET_USER':'','USENET_PASS':''},{})
        config={'services':{'infinidysk':{'environment':{'NZBDAV_CONFIG__USENET__PROVIDERS':'existing'}}}}
        self.assertEqual(apply_to_compose(config,values)['services']['infinidysk']['environment']['NZBDAV_CONFIG__USENET__PROVIDERS'],'existing')
    def test_incomplete_or_invalid_accounts_fail_without_echoing_secrets(self):
        for change in ({'USENET_HOST':''},{'USENET_PORT':'0'},{'USENET_CONNECTIONS':'0'},{'USENET_SSL':'maybe'},{'USENET_PASS':'bad\nfixture-secret'}):
            values=self.settings()
            with self.assertRaises(ValueError) as error:form_updates(change,values)
            self.assertNotIn('fixture-secret',str(error.exception))

    def test_extra_provider_and_indexer_keep_secrets_on_edit_and_support_removal(self):
        values = self.settings()
        values.update(form_updates({
            'USENET_EXTRA_SERVERS': [{'host': 'backup.fixture.invalid', 'username': 'backup-user',
                                      'password': 'backup$secret', 'backupOnly': True}],
            'USENET_EXTRA_INDEXERS': [{'url': 'https://index.fixture.invalid/', 'apiKey': 'indexer$secret'}],
        }, values))
        public = public_settings(values)
        self.assertNotIn('$secret', json.dumps(public))
        servers = public['USENET_EXTRA_SERVERS']
        indexers = public['USENET_EXTRA_INDEXERS']
        self.assertTrue(servers[0]['secretSaved'])
        self.assertTrue(indexers[0]['secretSaved'])
        servers[0]['connections'] = '3'
        values.update(form_updates({'USENET_EXTRA_SERVERS': servers, 'USENET_EXTRA_INDEXERS': indexers}, values))
        primary, backup = provider_config(values)['Providers']
        self.assertEqual((primary['Type'], backup['Type'], backup['MaxConnections']), (1, 3, 3))
        self.assertEqual(backup['Pass'], 'backup$secret')
        values.update(form_updates({'USENET_EXTRA_SERVERS': []}, values))
        self.assertEqual(len(provider_config(values)['Providers']), 1)

    def test_duplicate_indexer_addresses_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'appears more than once'):
            form_updates({'NZB_INDEXER_URL': 'https://index.fixture.invalid',
                          'USENET_EXTRA_INDEXERS': [{'url': 'https://index.fixture.invalid/', 'apiKey': 'fixture-key'}]}, {})

    def test_input_boundaries_and_error_hardening(self):
        # Non-dict inputs rejected gracefully
        with self.assertRaisesRegex(ValueError, 'Form updates require dictionaries'):
            form_updates("not a dict", {})
        with self.assertRaisesRegex(ValueError, 'Form updates require dictionaries'):
            form_updates({}, "not a dict")

        # Corrupted base64 credentials handled safely
        from tools.usenet_config import credential, extra_sources
        self.assertEqual(credential({}, 'USENET_USER'), '')
        self.assertEqual(credential("not a dict", 'USENET_USER'), '')
        with self.assertRaisesRegex(ValueError, 'Invalid stored Usenet credential'):
            credential({'USENET_USER_B64': '!!!invalid-base64'}, 'USENET_USER')

        # Corrupted extra sources
        self.assertEqual(extra_sources({}, 'USENET_EXTRA_SERVERS'), [])
        self.assertEqual(extra_sources("not a dict", 'USENET_EXTRA_SERVERS'), [])
        with self.assertRaisesRegex(ValueError, 'Invalid stored Usenet sources'):
            extra_sources({'USENET_EXTRA_SERVERS_B64': 'invalid-b64-content'}, 'USENET_EXTRA_SERVERS')

        # Indexer address boundary validation
        from tools.usenet_config import indexer_address
        with self.assertRaisesRegex(ValueError, 'indexer base address'):
            indexer_address(12345)
        with self.assertRaisesRegex(ValueError, 'indexer base address'):
            indexer_address("http://indexer.test\x00/api")
        with self.assertRaisesRegex(ValueError, 'indexer base address'):
            indexer_address("http://indexer.test:999999/")
