"""Disposable-stack upgrade/rollback acceptance; never uses the user's installation."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import release_manager as releases
PROJECT='aio-package'
BASE=ROOT.parent/'AIOStreams-Package-Test'
ENV=BASE/'.env'
fixture_env=dict(line.split('=',1) for line in ENV.read_text().splitlines() if '=' in line and not line.startswith('#'))
assert fixture_env.get('ADDON_PASSWORD')=='package-test-only-password','Refusing non-fixture deployment'
assert not any(fixture_env.get(k) for k in ('PREMIUMIZE_API_KEY','TMDB_API_KEY','TVDB_API_KEY','FANART_API_KEY'))
V1=BASE/'milestone/compose-v1.yml';V2=BASE/'milestone/compose-v2.yml';BAD=BASE/'milestone/compose-bad.yml'
def docker(*args):return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.PIPE).strip()
def identity():
 code="import json,hashlib;from pathlib import Path;p=json.loads(Path('/app/data/aiostreams/aiostreams_install.json').read_text());print(hashlib.sha256(json.dumps([p['uuid'],p.get('encrypted_password')]).encode()).hexdigest())"
 return docker('exec','aio-package-portal-1','python3','-c',code)
def sql(statement):return docker('exec','aio-package-shared-postgres-1','psql','-U','postgres','-d','aiometadata','-At','-v','ON_ERROR_STOP=1','-c',statement)
def args(current,target,folder):return argparse.Namespace(project=PROJECT,env_file=str(ENV),current=str(current),target=str(target),backup_dir=str(BASE/'milestone'/folder),allow_local=True)
def rollback(state):return releases.rollback(argparse.Namespace(project=PROJECT,env_file=str(ENV),state=str(state),allow_local=True))
subprocess.run(['docker','compose','-p',PROJECT,'--env-file',str(ENV),'-f',str(V1),'up','-d','--remove-orphans','--wait','--wait-timeout','600'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
print('Baseline pinned release healthy',flush=True)
releases.controller(args(V1,V2,'unused'),V1)
original=identity()
sql('CREATE TABLE IF NOT EXISTS release_fixture_sentinel(value text)')
sql("TRUNCATE release_fixture_sentinel; INSERT INTO release_fixture_sentinel VALUES ('before-upgrade')")
good=args(V1,V2,'upgrade-success');releases.upgrade(good)
assert identity()==original
assert sql('SELECT value FROM release_fixture_sentinel')=='before-upgrade'
print('PASS: upgrade preserves profile identity and database state',flush=True)
sql("UPDATE release_fixture_sentinel SET value='after-upgrade'")
rollback(Path(good.backup_dir)/'upgrade-state.json')
assert sql('SELECT value FROM release_fixture_sentinel')=='before-upgrade'
assert identity()==original
print('PASS: rollback restores baseline images and snapshot data',flush=True)
bad=args(V1,BAD,'upgrade-failure')
try:releases.upgrade(bad)
except RuntimeError:pass
else:raise AssertionError('Injected release lock failure unexpectedly succeeded')
state=Path(bad.backup_dir)/'upgrade-state.json'
assert json.loads(state.read_text())['status']=='failed'
rollback(state)
assert identity()==original
assert sql('SELECT value FROM release_fixture_sentinel')=='before-upgrade'
print('PASS: failed upgrade recovery preserves profile identity and database state',flush=True)
sql('DROP TABLE release_fixture_sentinel')
