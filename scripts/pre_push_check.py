#!/usr/bin/env python3
"""Comprehensive pre-push release verification gate.

Runs all local validations before git push:
1. Validates compose.manager.yml freshness
2. Runs check_inventory and check_integrations
3. Executes complete Python unit test suite
4. Executes Node.js UI and browser test suite (if node is installed)
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run_gate(name, cmd):
    print(f"==> [Gate] Running {name}...", flush=True)
    res = subprocess.run(cmd, shell=False)
    if res.returncode != 0:
        print(f"\n==> [ERROR] {name} failed with exit code {res.returncode}!", file=sys.stderr, flush=True)
        return False
    return True


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["AIO_SKIP_ENV_FILE"] = "true"

    # 1. Compose manager freshness
    if not run_gate("Manager Compose Freshness", [sys.executable, "scripts/generate_manager_compose.py", "--check"]):
        print("==> Fix: Run 'python scripts/generate_manager_compose.py' and commit compose.manager.yml", file=sys.stderr)
        return 1

    # 2. Inventory check
    if not run_gate("Service Inventory Check", [sys.executable, "-m", "tests.check_inventory"]):
        return 1

    # 3. Integrations check
    if not run_gate("Integrations Check", [sys.executable, "-m", "tests.check_integrations"]):
        return 1

    # 4. Full Python unit test discovery
    if not run_gate("Full Python Unit Tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]):
        return 1

    # 5. Node.js browser and UI tests (if node is available)
    if shutil.which("node"):
        if not run_gate("Browser & UI Tests", [
            "node", "--test",
            "tests/browser-bootstrap.test.cjs",
            "tests/maintenance-ui.test.cjs",
            "tests/optional-setup-ui.test.cjs"
        ]):
            return 1

    print("\n==> [SUCCESS] All pre-push release gates passed cleanly!", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
