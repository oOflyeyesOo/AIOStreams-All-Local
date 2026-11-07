"""Immutable release bundles and backup-gated upgrades. No credentials in lock files."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

PIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[0-9a-f]{64}$')
LOCAL = re.compile(r'^sha256:[0-9a-f]{64}$')

def validate_lock(lock, *, local=False):
    if not isinstance(lock,dict) or lock.get('format')!='aio-release-v1':raise ValueError('Unsupported release lock')
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',str(lock.get('release',''))):raise ValueError('Invalid release identifier')
    local = local or lock.get('localOnly') is True
    images=lock.get('images')
    if not isinstance(images,dict) or not images:raise ValueError('Release has no image set')
    for name,image in images.items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',name) or not isinstance(image,str) or not (PIN.fullmatch(image) or (local and LOCAL.fullmatch(image))):
            raise ValueError('Release images must be immutable digests')
    return lock

def encoded_lock(lock):
    validate_lock(lock)
    return base64.b64encode(json.dumps(lock,separators=(',',':')).encode()).decode()

def decode_lock(value):
    if len(value)>65536:raise ValueError('Release lock is too large')
    return validate_lock(json.loads(base64.b64decode(value,validate=True)))

def apply_images(config, lock):
    validate_lock(lock)
    expected={name for name,svc in config['services'].items() if svc.get('image')}
    if set(lock['images'])!=expected:raise ValueError('Release image set does not match this Compose definition')
    for name,image in lock['images'].items():config['services'][name]['image']=image
    return config

def preview(current, target):
    validate_lock(current);validate_lock(target)
    changes=[{'service':name,'from':current['images'].get(name),'to':image}
             for name,image in target['images'].items() if current['images'].get(name)!=image]
    return {'current':current['release'],'target':target['release'],'changes':changes,
            'removedServices':sorted(set(current['images'])-set(target['images'])),
            'backupRequired':True,'migrations':'Review release notes; database downgrade compatibility is not inferred from image tags.'}

def command(args, *, timeout=900, data=None, env=None):
    result=subprocess.run(args,input=data,capture_output=True,text=True,timeout=timeout,env=env)
    if result.returncode:raise RuntimeError('Command failed: '+args[0]+' '+(' '.join(args[1:3])))
    return result.stdout

def resolve_image(image):
    if PIN.fullmatch(image):return image
    output=command(['docker','buildx','imagetools','inspect',image],timeout=120)
    match=re.search(r'^Digest:\s+(sha256:[0-9a-f]{64})',output,re.M)
    if not match:raise RuntimeError('Registry did not return an immutable digest')
    repository=image.split('@',1)[0]
    if ':' in repository.rsplit('/',1)[-1]:repository=repository.rsplit(':',1)[0]
    return repository+'@'+match[1]

def load_compose(path):
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))

def make_bundle(compose_path,release,output,resolver=resolve_image):
    import yaml
    source=load_compose(compose_path)
    # Ask Compose to resolve image variables only in memory; never persist env values.
    resolved=json.loads(command(['docker','compose','--env-file','.env.example','-f',str(compose_path),'--profile','*','config','--format','json'],env=dict(os.environ,AIO_IMAGE_TAG=release)))
    cache={};images={}
    for name,service in resolved['services'].items():
        if 'image' not in service:raise ValueError('Release bundles cannot contain build-only services')
        ref=service['image']
        if ref not in cache:cache[ref]=resolver(ref)
        images[name]=cache[ref]
    lock=validate_lock({'format':'aio-release-v1','release':release,'images':images})
    for name,image in images.items():source['services'][name]['image']=image
    for name in ('portal','controller'):
        env=source['services'][name].setdefault('environment',[])
        if not isinstance(env,list):raise ValueError('Expected list environment in generated manager definition')
        source['services'][name]['environment']=[v for v in env if not v.startswith(('AIO_RELEASE_LOCK_B64=','AIO_IMAGE_TAG='))]+['AIO_RELEASE_LOCK_B64='+encoded_lock(lock),'AIO_IMAGE_TAG='+release]
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'release.lock.json').write_text(json.dumps(lock,indent=2)+'\n',encoding='utf-8')
    (output/'compose.release.yml').write_text(yaml.safe_dump(source,sort_keys=False),encoding='utf-8')
    return lock

def verify_backup(path):
    import tarfile
    try:
        with tarfile.open(path,'r:gz') as archive:
            manifest=json.load(archive.extractfile('backup-manifest.json'))
            if not manifest.get('postgresIncluded'):
                raise RuntimeError('Refusing upgrade: backup lacks PostgreSQL')
            for name in ('postgres_cluster.sql','.env','data/aiostreams/db.sqlite','data/aiostreams/aiostreams_install.json'):
                if archive.getmember(name).size<=0:raise RuntimeError('Refusing upgrade: backup is incomplete')
    except (KeyError,tarfile.TarError,ValueError) as error:
        raise RuntimeError('Refusing upgrade: backup is incomplete or invalid') from error
    digest=hashlib.sha256()
    with open(path,'rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def compose(args,path):
    result=['docker','compose','-p',args.project]
    if args.env_file:result+=['--env-file',str(Path(args.env_file).resolve())]
    return result+['-f',str(Path(path).resolve())]

def portal_id(args,path):
    ids=command(compose(args,path)+['ps','-q','portal']).split()
    if len(ids)!=1:raise RuntimeError('Expected one portal in selected project')
    return ids[0]

def save_private(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as output:json.dump(data,output,indent=2)

def controller(args,path):
    portal=portal_id(args,path)
    code="import importlib.util,json;s=importlib.util.spec_from_file_location('portal','/usr/local/lib/aio/portal_server.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
    result=json.loads(command(['docker','exec',portal,'python3','-c',code+"print(json.dumps(m.control_request('POST','/apply')))"]))
    if result[0]!=202:raise RuntimeError('Controller did not accept configuration apply')
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        result=json.loads(command(['docker','exec',portal,'python3','-c',code+"r=m.control_request('GET','/status');print(json.dumps({'status':r[1]['status']}))"]))
        if result['status']=='complete':return
        if result['status']=='failed':raise RuntimeError('Controller configuration failed; inspect portal details')
        time.sleep(2)
    raise RuntimeError('Controller apply timed out')

def check_pinned(path,local=False):
    config=load_compose(path)
    for service in config['services'].values():
        image=service.get('image','')
        if service.get('build') or not (PIN.fullmatch(image) or (local and LOCAL.fullmatch(image))):raise ValueError('Use an immutable image-only release Compose file')
    return config

def upgrade(args):
    check_pinned(args.current,args.allow_local);check_pinned(args.target,args.allow_local)
    portal=portal_id(args,args.current)
    directory=Path(args.backup_dir).resolve();directory.mkdir(parents=True,exist_ok=True)
    code="import sys;sys.path.insert(0,'/app');from tools.backup import create_backup;print(create_backup().name)"
    name=command(['docker','exec',portal,'python3','-c',code]).strip().splitlines()[-1]
    if Path(name).name!=name or not re.fullmatch(r'aio-backup-[A-Za-z0-9.-]+\.tar\.gz',name):raise RuntimeError('Unexpected backup filename')
    archive=directory/name
    command(['docker','cp',portal+':/app/backups/'+name,str(archive)])
    os.chmod(archive,0o600)
    checksum=verify_backup(archive)
    previous=directory/'previous.compose.yml';previous.write_bytes(Path(args.current).read_bytes());os.chmod(previous,0o600)
    restorer=command(['docker','inspect',portal,'--format','{{.Image}}']).strip()
    state={'format':'aio-upgrade-v1','project':args.project,'previous':str(previous),'target':str(Path(args.target).resolve()),
           'archive':str(archive),'archiveName':name,'backupSha256':checksum,'restoreImage':restorer,'status':'backup-verified'}
    state_path=directory/'upgrade-state.json';save_private(state_path,state)
    try:
        if args.allow_local:
            for image in {svc['image'] for svc in load_compose(args.target)['services'].values()}:
                command(['docker','image','inspect',image,'--format','{{.Id}}'])
        else:command(compose(args,args.target)+['pull'])
        state['status']='applying';save_private(state_path,state)
        command(compose(args,args.target)+['up','-d','--remove-orphans','--wait','--wait-timeout','600'])
        controller(args,args.target)
        state['status']='complete';save_private(state_path,state)
    except Exception:
        state['status']='failed';save_private(state_path,state);raise
    print('Upgrade complete. Recovery state: '+str(state_path))

def rollback(args):
    state=json.loads(Path(args.state).read_text())
    if state.get('format')!='aio-upgrade-v1' or state['project']!=args.project:raise ValueError('Recovery state project mismatch')
    if verify_backup(state['archive'])!=state['backupSha256']:raise ValueError('Backup changed after upgrade; refusing restore')
    config=check_pinned(state['previous'],args.allow_local)
    portal=portal_id(args,state['target'])
    keep={'portal','controller','shared-postgres','shared-redis'}
    current=load_compose(state['target'])
    stop=[name for name in current['services'] if name not in keep]
    command(compose(args,state['target'])+['stop']+stop)
    command(['docker','cp',state['archive'],portal+':/app/backups/'+state['archiveName']])
    code="import sys;from pathlib import Path;sys.path.insert(0,'/opt/aio');from tools.backup import restore_backup;sys.exit(0 if restore_backup(Path('/app/backups')/sys.argv[1],Path('/app')) else 1)"
    command(['docker','run','--rm','--volumes-from',portal,'-e','AIO_PROJECT_NAME='+args.project,'--entrypoint','python3',state['restoreImage'],'-c',code,state['archiveName']])
    command(compose(args,state['previous'])+['up','-d','--remove-orphans','--wait','--wait-timeout','600'])
    controller(args,state['previous'])
    state['status']='rolled-back';save_private(args.state,state)
    print('Rollback complete; restored data and previous images.')

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    bundle=sub.add_parser('bundle');bundle.add_argument('--compose',default='compose.manager.yml');bundle.add_argument('--release',required=True);bundle.add_argument('--output',required=True)
    view=sub.add_parser('preview');view.add_argument('current');view.add_argument('target')
    for name in ('upgrade','rollback'):
        item=sub.add_parser(name);item.add_argument('--project',required=True);item.add_argument('--env-file');item.add_argument('--allow-local',action='store_true')
        if name=='upgrade':item.add_argument('--current',required=True);item.add_argument('--target',required=True);item.add_argument('--backup-dir',required=True)
        else:item.add_argument('--state',required=True)
    args=parser.parse_args()
    if args.action=='bundle':make_bundle(args.compose,args.release,args.output)
    elif args.action=='preview':print(json.dumps(preview(json.loads(Path(args.current).read_text()),json.loads(Path(args.target).read_text())),indent=2))
    else:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]+',args.project):raise ValueError('Invalid Compose project')
        (upgrade if args.action=='upgrade' else rollback)(args)

if __name__=='__main__':main()
