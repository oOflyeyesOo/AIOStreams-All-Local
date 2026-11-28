import copy
import json
import unittest
from unittest.mock import patch
from tools import player_users as users

class PlayerUsersTests(unittest.TestCase):
    def setUp(self):
        self.config = {'addonName': 'Owner', 'presets': [{'secret': 'fixture-provider-key'}], 'jellyfin': {'otherSetting': True, 'personas': []}}
        self.caps = {'enabled': True, 'pinSignIn': True, 'maxPersonas': 20}
        self.writes = 0
    def request(self, uuid, password, path, payload=None):
        if path == '/api/v1/status': return {'settings': {'jellyfin': self.caps}}
        if payload:
            self.writes += 1
            self.config = copy.deepcopy(payload['config'])
            for p in users._people(self.config):
                if str(p.get('lock', '')).isdigit(): p['lock'] = '$2b$fixture-hash'
        return {'userData': copy.deepcopy(self.config)}
    def mutate(self, **kwargs):
        return users.mutate_user('uuid', 'private', 'https://watch.example', {'expectedRevision': users._revision(self.config), **kwargs})
    def test_create_preserves_config_and_does_not_disclose_secrets(self):
        with patch.object(users, '_request', side_effect=self.request): result = self.mutate(action='create', name='Alex')
        self.assertRegex(result['pin'], r'^\d{8}$')
        person = self.config['jellyfin']['personas'][0]
        self.assertTrue(person['hidden']); self.assertEqual(person['history'], 'own')
        self.assertEqual(self.config['presets'][0]['secret'], 'fixture-provider-key')
        self.assertTrue(self.config['jellyfin']['otherSetting'])
        self.assertIn('/jellyfin/p/', result['inviteUrl']); self.assertTrue(result['inviteUrl'].endswith('/web/'))
        with patch.object(users, '_request', side_effect=self.request): listing = users.list_users('uuid','private','https://watch.example')
        self.assertNotIn('pin', listing); self.assertNotIn('fixture-provider-key', json.dumps(listing)); self.assertNotIn('$2b$', json.dumps(listing))
    def test_stale_or_concurrent_changes_never_write(self):
        with patch.object(users, '_request', side_effect=self.request):
            with self.assertRaises(users.PlayerUsersError): users.mutate_user('u','p','https://watch.example',{'action':'create','name':'Alex','expectedRevision':'old'})
        self.assertEqual(self.writes,0)
        count=0
        def concurrent(*args, **kwargs):
            nonlocal count
            if args[2].startswith('/api/v1/user'): count+=1
            if count==2: self.config['addonName']='External edit'
            return self.request(*args, **kwargs)
        with patch.object(users, '_request', side_effect=concurrent), self.assertRaises(users.PlayerUsersError): self.mutate(action='create',name='Alex')
        self.assertEqual(self.writes,0)
    def test_reset_link_replace_and_remove(self):
        with patch.object(users, '_request', side_effect=self.request):
            first=self.mutate(action='create',name='Alex'); uid=first['userId']
            reset=self.mutate(action='reset_pin',id=uid); self.assertIn('pin',reset)
            replaced=self.mutate(action='replace_link',id=uid);self.assertNotEqual(first['inviteUrl'],replaced['inviteUrl']);self.assertNotIn('pin',replaced)
            removed=self.mutate(action='remove',id=uid);self.assertEqual(removed['users'],[])
    def test_owner_household_duplicates_limits_and_disabled_are_protected(self):
        with patch.object(users, '_request', side_effect=self.request):
            for payload in ({'action':'remove','id':''},{'action':'create','name':'Owner'},{'action':'create','name':'x'*33}):
                with self.assertRaises(users.PlayerUsersError): self.mutate(**payload)
            self.config['jellyfin']['personas']=[{'id':'household','name':'Home'}]
            with self.assertRaises(users.PlayerUsersError): self.mutate(action='remove',id='household')
            self.caps['maxPersonas']=1
            with self.assertRaises(users.PlayerUsersError):self.mutate(action='create',name='Alex')
            self.caps['pinSignIn']=False
            with self.assertRaises(users.PlayerUsersError):self.mutate(action='create',name='Alex')
        self.assertEqual(self.writes,0)
    def test_new_profile_schema_preserves_owner_and_uses_native_profiles(self):
        owner = {'id': '', 'name': 'Owner', 'lock': 'owner-hash'}
        self.config['profiles'] = [owner]
        self.caps = {'enabled': True, 'pinSignIn': True, 'maxProfiles': 1}
        with patch.object(users, '_request', side_effect=self.request):
            result = self.mutate(action='create', name='Alex')
            self.assertEqual(len(result['users']), 1)
            self.assertEqual(self.config['profiles'][0], owner)
            self.assertEqual(self.config['jellyfin']['personas'], [])
            self.assertEqual(self.config['profiles'][1]['history'], 'own')
            with self.assertRaises(users.PlayerUsersError): self.mutate(action='create', name='Other')
            self.mutate(action='remove', id=result['userId'])
            self.assertEqual(self.config['profiles'], [owner])

    def test_removal_stays_available_with_pin_sign_in_disabled(self):
        with patch.object(users, '_request', side_effect=self.request):
            result = self.mutate(action='create', name='Alex')
            self.caps['pinSignIn'] = False
            self.assertEqual(self.mutate(action='remove', id=result['userId'])['users'], [])

    def test_mutation_http_errors_are_not_replayed_or_leaked(self):
        from urllib.error import HTTPError
        for status in (429, 401, 500):
            with patch.object(users, '_NEXT_USER_REQUEST', 0), patch.object(users._OPENER, 'open', side_effect=HTTPError('http://internal', status, 'secret-detail', {}, None)) as request:
                with self.assertRaises(users.PlayerUsersError) as caught:
                    users._request('owner', 'private', '/api/v1/user', {'config': {}})
                self.assertEqual(request.call_count, 1)
                self.assertNotIn('secret-detail', str(caught.exception))
                self.assertNotIn('private', str(caught.exception))

    def test_invalid_public_origin_is_rejected(self):
        for base in ('javascript:alert(1)','https://owner:secret@example.com','https://example.com/owner-secret','https://example.com/?secret=x'):
            with self.assertRaises(users.PlayerUsersError):users.list_users('', '', base)
