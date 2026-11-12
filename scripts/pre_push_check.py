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
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
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

    # 6. Compose definitions & profile validation (if docker is available)
    if shutil.which("docker"):
        compose_files = [
            "docker-compose.yml",
            "docker-compose.aio.yml",
            "compose.manager.yml",
            "compose.test.yml",
            "compose.tools.yml",
        ]
        for cf in compose_files:
            if not run_gate(f"Compose Config Validation ({cf})", ["docker", "compose", "--env-file", ".env.example", "-f", cf, "config", "--quiet"]):
                return 1

        for profile in ["core", "scrapers", "nuvio", "tunnel", "all"]:
            if not run_gate(f"Compose Profile Validation ({profile})", ["docker", "compose", "--env-file", ".env.example", "--profile", profile, "config", "--quiet"]):
                return 1

    # 7. Release Manager compose parsing verification
    from tools import release_manager
    try:
        release_manager.load_compose("compose.manager.yml")
        release_manager.load_compose("docker-compose.yml")
    except Exception as e:
        print(f"\n==> [ERROR] Release Manager Compose Parsing failed: {e}!", file=sys.stderr, flush=True)
        return 1

    # 8. PowerShell update script check (if pwsh is available on Windows/Linux)
    if shutil.which("pwsh"):
        if not run_gate("PowerShell Update Scripts Check", ["pwsh", "./tests/check_update_scripts.ps1"]):
            return 1

    print("\n==> [SUCCESS] All pre-push release gates passed cleanly!", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
