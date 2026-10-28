import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class DatabaseFailureTests(unittest.TestCase):
    def run_initializer(self, ready_exit, psql_script):
        with tempfile.TemporaryDirectory() as directory:
            for name, source in (("pg_isready", f"exit {ready_exit}"), ("psql", psql_script)):
                target = Path(directory) / name
                target.write_text("#!/bin/sh\n" + source + "\n")
                target.chmod(0o755)
            env = dict(os.environ, PATH=directory + ":" + os.environ["PATH"], DB_WAIT_RETRIES="1")
            script = Path(__file__).resolve().parents[1] / "init/postgres/init-databases.sh"
            return subprocess.run(["sh", str(script)], env=env, capture_output=True, timeout=5)

    def test_unavailable_database_fails(self):
        self.assertNotEqual(self.run_initializer(1, "exit 1").returncode, 0)

    def test_query_failure_fails(self):
        result = self.run_initializer(0, 'case "$*" in *"SELECT 1;"*) exit 0;; *) exit 1;; esac')
        self.assertNotEqual(result.returncode, 0)

    def test_create_failure_fails(self):
        result = self.run_initializer(0, 'case "$*" in *"CREATE DATABASE"*) exit 1;; *) exit 0;; esac')
        self.assertNotEqual(result.returncode, 0)
