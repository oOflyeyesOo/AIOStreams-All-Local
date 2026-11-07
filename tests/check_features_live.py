"""Exercise maintenance APIs only in the disposable aio-package deployment."""
import base64,io,json,os,tarfile,tempfile,urllib.request,urllib.error
from pathlib import Path
assert os.environ.get('AIO_PROJECT_NAME')=='aio-package'
auth='Basic '+base64.b64encode(('admin:'+os.environ['ADDON_PASSWORD']).encode()).decode()
def call(path,method='GET',origin=None,authenticated=True):
 headers={'Authorization':auth} if authenticated else {}
 if origin:headers['Origin']=origin
 try:
  response=urllib.request.urlopen(urllib.request.Request('http://localhost:8088'+path,method=method,headers=headers),timeout=300)
  return response.status,response.read(),dict(response.headers)
 except urllib.error.HTTPError as error:return error.code,error.read(),dict(error.headers)
assert call('/api/backup',authenticated=False)[0]==401
assert call('/api/clean-cache')[0]==405
assert call('/api/clean-cache','POST',origin='https://untrusted.example')[0]==403
status,body,_=call('/api/resources');stats=json.loads(body)
assert status==200 and stats['success'] and all(x['name'].startswith('aio-package-') for x in stats['containers'])
env=Path('/app/.env');original=env.read_bytes()
try:
 for value in ('first-fixture','updated-fixture'):
  env.write_bytes(original+b'\nFEATURE_BACKUP_SENTINEL='+value.encode()+b'\n')
  status,body,headers=call('/api/backup')
  assert status==200 and headers.get('Cache-Control')=='no-store'
  with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as tar:
   assert tar.getmember('postgres_cluster.sql').size>0
   assert tar.getmember('data/prowlarr/prowlarr.db').size>0
   assert ('FEATURE_BACKUP_SENTINEL='+value) in tar.extractfile('.env').read().decode()
   assert json.load(tar.extractfile('backup-manifest.json'))['postgresIncluded']
 print('PASS: live backup auth, current configuration in repeated downloads, PostgreSQL and Prowlarr coverage')
finally:env.write_bytes(original)
cache=Path('/app/data/stremthru/cache')
cache.mkdir(parents=True,exist_ok=True);(cache/'feature-test-sentinel.tmp').write_text('fixture')
status,body,_=call('/api/clean-cache','POST')
assert status==200 and json.loads(body)['success']
assert not (cache/'feature-test-sentinel.tmp').exists()
assert Path('/app/data/prowlarr/prowlarr.db').exists()
print('PASS: project-scoped resources, POST-only cleanup, cross-origin rejection, live cache cleanup')
