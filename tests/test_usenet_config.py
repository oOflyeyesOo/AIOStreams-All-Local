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
