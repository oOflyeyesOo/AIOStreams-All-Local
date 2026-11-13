"""Verify that the shared application inventory matches the Compose services."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from init.service_inventory import INTEGRATIONS


def main():
    result = subprocess.run(
        ["docker", "compose", "--env-file", ".env.example", "--profile", "all", "config", "--services"],
        check=True,
        capture_output=True,
        text=True,
    )
    services = set(result.stdout.split())
    missing = sorted({host for _, host, _, _ in INTEGRATIONS} - services)
    if missing:
        print("Inventory services missing from Compose: " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"Verified {len(INTEGRATIONS)} inventoried application services.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
