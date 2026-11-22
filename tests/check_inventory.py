"""Verify that the shared application inventory matches the Compose services."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from init.service_inventory import APPLICATION_SERVICE_COUNT, INTEGRATIONS


def main():
    result = subprocess.run(
        ["docker", "compose", "--env-file", ".env.example", "--profile", "all", "config", "--services"],
        check=True,
        capture_output=True,
        text=True,
    )
    services = set(result.stdout.split())
    inventory_hosts = {host for _, host, _, _ in INTEGRATIONS}
    missing = sorted(inventory_hosts - services)
    if missing:
        print("Inventory services missing from Compose: " + ", ".join(missing), file=sys.stderr)
        return 1
    if "infinidysk" in inventory_hosts:
        print("InfiniDysk must not be in service inventory", file=sys.stderr)
        return 1
    if len(INTEGRATIONS) != APPLICATION_SERVICE_COUNT:
        print(f"INTEGRATIONS length ({len(INTEGRATIONS)}) does not match APPLICATION_SERVICE_COUNT ({APPLICATION_SERVICE_COUNT})", file=sys.stderr)
        return 1
    print(f"Verified {len(INTEGRATIONS)} inventoried application services.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
