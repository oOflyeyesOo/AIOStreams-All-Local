"""Destructive restore acceptance; run only with AIO_PROJECT_NAME=aio-feature-tests."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import backup
assert os.environ.get('AIO_PROJECT_NAME')=='aio-feature-tests'
container=backup.postgres_container()
def sql(database,statement):
 return subprocess.check_output(['docker','exec',container,'psql','-U','postgres','-d',database,'-v','ON_ERROR_STOP=1','-At','-c',statement]).decode().strip()
sql('postgres','DROP DATABASE IF EXISTS feature_fixture')
sql('postgres','CREATE DATABASE feature_fixture')
sql('feature_fixture',"CREATE TABLE sentinel(value text); INSERT INTO sentinel VALUES ('survives restore')")
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder)/'source';(root/'data/prowlarr').mkdir(parents=True)
 (root/'.env').write_text('ADDON_PASSWORD=fixture-only\n')
 with sqlite3.connect(root/'data/prowlarr/prowlarr.db') as db:
  db.execute('CREATE TABLE sentinel(value text)');db.execute("INSERT INTO sentinel VALUES ('saved indexers')");db.commit()
 archive=backup.create_backup(root=root)
 with tarfile.open(archive) as tar:assert tar.getmember('postgres_cluster.sql').size>0
 sql('postgres','DROP DATABASE feature_fixture')
 assert backup.restore_backup(archive,Path(folder)/'restored')
 assert sql('feature_fixture','SELECT value FROM sentinel')=='survives restore'
 with sqlite3.connect(Path(folder)/'restored/data/prowlarr/prowlarr.db') as db:assert db.execute('SELECT value FROM sentinel').fetchone()[0]=='saved indexers'
 invalid=Path(folder)/'invalid.sql';invalid.write_text('INVALID SQL;')
 assert not backup.restore_postgres(invalid)
 print('PASS: PostgreSQL dump/drop/restore, SQLite data, environment and invalid-SQL rejection')
