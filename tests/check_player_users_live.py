"""Native invitation acceptance against the disposable no-provider fixture only."""
import base64
import json
import os
import time
import sys
from pathlib import Path
import urllib.request
import urllib.error
import urllib.parse


def main():
    assert os.environ.get('AIO_FRESH_INSTALL_TEST') == 'true'
    assert os.environ.get('AIO_FRESH_INSTALL_TEST_PROJECT') == 'aio-fresh-install'
    portal = 'http://127.0.0.1:8088'
    core = 'http://aiostreams:3000'
    auth = 'Basic ' + base64.b64encode(b'admin:package-test-only-password').decode()
    def request(url, data=None, token=None, admin=False):
        headers={'Content-Type':'application/json'}
        if admin: headers['Authorization']=auth
        if token: headers['X-Emby-Token']=token
        req=urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=20) as r:
                body=r.read();return r.status, json.loads(body) if body and 'application/json' in r.headers.get('Content-Type','') else None
        except urllib.error.HTTPError as e:
            return e.code,{'error': json.loads(e.read()).get('error', 'Request rejected')} if e.headers.get('Content-Type','').startswith('application/json') else None
    def listing():
        code,data=request(portal+'/api/player-users',admin=True)
        assert code==200, 'Owner user list failed: '+str(code)+' '+str(data)
        return data
    def mutate(action, **kw):
        code,data=request(portal+'/api/player-users',{'action':action,'expectedRevision':listing()['revision'],**kw},admin=True)
        assert code==200, 'Owner user action failed: '+action+' '+str(code)+' '+str(data)
        return data
    def mount(invite): return core+urllib.parse.urlsplit(invite).path.removesuffix('/web/')
    def login(base,name,pin):return request(base+'/Users/AuthenticateByName',{'Username':name,'Pw':pin})
    persistence = Path('/app/data/aiostreams/invite_acceptance.json')
    if '--verify-restart' in sys.argv:
        saved=json.loads(persistence.read_text())
        assert login(mount(saved['inviteUrl']), 'Guest Restart', saved['pin'])[0]==200, 'Guest did not survive recreation'
        mutate('remove', id=saved['userId'])
        persistence.unlink()
        print('PASS: guest PIN and isolated link survived portal and AIOStreams restart')
        return
    assert request(portal+'/api/player-users')[0]==401
    assert request(portal+'/api/player-users',{'action':'create','name':'Denied'})[0]==401
    for user in listing()['users']:
        assert user['name'] in ('Guest Alpha', 'Guest Beta', 'Guest Restart'), 'Unexpected users in disposable fixture'
        mutate('remove', id=user['id'])
    a=mutate('create',name='Guest Alpha'); b=mutate('create',name='Guest Beta')
    def mount(invite): return core+urllib.parse.urlsplit(invite).path.removesuffix('/web/')
    ma,mb=mount(a['inviteUrl']),mount(b['inviteUrl'])
    def login(base,name,pin):return request(base+'/Users/AuthenticateByName',{'Username':name,'Pw':pin})
    assert request(ma+'/web/')[0]==200, 'Invite browser page unavailable'
    code,public=request(ma+'/Users/Public');assert code==200 and len(public)==1 and public[0]['Name']=='Guest Alpha', 'Picker leaked another profile'
    code,session=login(ma,'Guest Alpha',a['pin']);assert code==200, 'Guest PIN sign-in failed'
    token=session['AccessToken']
    code,views=request(ma+'/Users/'+session['User']['Id']+'/Views',token=token)
    assert code==200 and views.get('Items'), 'Guest did not inherit owner catalogs'
    code,people=request(ma+'/Users',token=token);assert code==200 and len(people)==1 and people[0]['Name']=='Guest Alpha', 'Guest user list leaked owner or another guest'
    assert login(ma,'Guest Beta',b['pin'])[0]==401, 'Guest switched to another profile'
    assert login(ma,'Owner',a['pin'])[0]==401
    code,all_users=request(portal+'/api/player-users',admin=True);assert code==200 and 'pin' not in all_users
    reset=mutate('reset_pin',id=a['userId'])
    assert login(ma,'Guest Alpha',a['pin'])[0]==401, 'Old PIN survived reset'
    deadline=time.monotonic()+40
    code=request(ma+'/Users/Me',token=token)[0]
    while code==200 and time.monotonic()<deadline:
        time.sleep(2)
        code=request(ma+'/Users/Me',token=token)[0]
    assert code in (401,403,404), 'Old session survived PIN reset: '+str(code)
    code,session=login(ma,'Guest Alpha',reset['pin']);assert code==200
    new=mutate('replace_link',id=a['userId']);new_mount=mount(new['inviteUrl'])
    assert new_mount!=ma
    deadline=time.monotonic()+40
    code=request(ma+'/Users/Public')[0]
    while code==200 and time.monotonic()<deadline:
        time.sleep(2);code=request(ma+'/Users/Public')[0]
    assert code in (401,403,404), 'Old address survived replacement'
    assert login(new_mount,'Guest Alpha',reset['pin'])[0]==200
    token=login(mb,'Guest Beta',b['pin'])[1]['AccessToken']
    mutate('remove',id=b['userId'])
    deadline=time.monotonic()+40
    code=request(mb+'/Users/Me',token=token)[0]
    while code==200 and time.monotonic()<deadline:
        time.sleep(2);code=request(mb+'/Users/Me',token=token)[0]
    assert code in (401,403,404), 'Removed guest session still works'
    mutate('remove',id=a['userId'])
    persistent=mutate('create',name='Guest Restart')
    persistence.write_text(json.dumps({k:persistent[k] for k in ('userId','pin','inviteUrl')}))
    persistence.chmod(0o600)
    print('PASS: two native invites, browser page, PIN sign-in, guest isolation, PIN/session revocation, link replacement and removal')

if __name__=='__main__':
    main()
