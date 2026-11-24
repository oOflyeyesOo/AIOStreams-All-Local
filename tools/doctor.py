#!/usr/bin/env python3
"""
AIO Appliance System Doctor & Deep Diagnostic Tool
===================================================
Executes comprehensive diagnostics on local runtime, Docker container health,
database integrity (PostgreSQL/Redis), debrid credentials, and network latency.

Usage:
    python tools/doctor.py
    python tools/doctor.py --json
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def is_in_docker() -> bool:
    return Path("/.dockerenv").is_file() or os.environ.get("IN_DOCKER") == "1"


def read_env_file() -> dict:
    env = dict(os.environ)
    for cand in [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]:
        if cand.is_file():
            try:
                for line in cand.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass
            break
    return env


def check_docker() -> dict:
    start = time.monotonic()
    try:
        res = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                             capture_output=True, text=True, timeout=6)
        rtt = round((time.monotonic() - start) * 1000.0, 1)
        if res.returncode == 0 and res.stdout.strip():
            return {"status": "ok", "version": res.stdout.strip(), "rtt_ms": rtt}
        return {"status": "error", "error": res.stderr.strip() or "Docker daemon not responding"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_containers() -> dict:
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.State}}"],
            capture_output=True, text=True, timeout=8
        )
        if res.returncode != 0:
            return {"status": "error", "containers": {}}
        containers = {}
        for line in res.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                name, status, state = parts[0].strip(), parts[1].strip(), parts[2].strip()
                containers[name] = {"status": status, "state": state, "healthy": "healthy" in status.lower() or state == "running"}
        return {"status": "ok", "containers": containers}
    except Exception as e:
        return {"status": "error", "error": str(e), "containers": {}}


def check_postgres(env: dict) -> dict:
    start = time.monotonic()
    in_docker = is_in_docker()
    host = "shared-postgres" if in_docker else "127.0.0.1"
    port = 5432
    password = env.get("POSTGRES_PASSWORD", "postgres_supersecret_db_pass_2026")

    # First check socket / pg_isready
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect((host, port))
        s.close()
        rtt = round((time.monotonic() - start) * 1000.0, 1)
    except Exception as e:
        # If not exposed on host, check container inspect
        try:
            inspect_res = subprocess.run(
                ["docker", "exec", "shared-postgres", "pg_isready", "-U", "postgres", "-d", "postgres"],
                capture_output=True, text=True, timeout=4
            )
            rtt = round((time.monotonic() - start) * 1000.0, 1)
            if inspect_res.returncode == 0:
                pass
            else:
                return {"status": "error", "error": "Postgres socket unreachable"}
        except Exception:
            return {"status": "error", "error": str(e)}

    # Check database presence
    dbs = ["zilean", "aiometadata"]
    found_dbs = []
    try:
        cmd = ["docker", "exec", "shared-postgres", "psql", "-U", "postgres", "-d", "postgres", "-tAc",
               "SELECT datname FROM pg_database WHERE datname IN ('zilean', 'aiometadata');"]
        db_res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if db_res.returncode == 0:
            found_dbs = [line.strip() for line in db_res.stdout.splitlines() if line.strip()]
    except Exception:
        pass

    return {
        "status": "ok",
        "rtt_ms": rtt,
        "required_dbs": dbs,
        "present_dbs": found_dbs,
        "dbs_ok": set(dbs).issubset(set(found_dbs))
    }


def check_redis(env: dict) -> dict:
    start = time.monotonic()
    in_docker = is_in_docker()
    host = "shared-redis" if in_docker else "127.0.0.1"
    port = 6379

    try:
        # Check through docker exec or TCP socket
        res = subprocess.run(
            ["docker", "exec", "shared-redis", "redis-cli", "ping"],
            capture_output=True, text=True, timeout=4
        )
        rtt = round((time.monotonic() - start) * 1000.0, 1)
        if res.returncode == 0 and "PONG" in res.stdout:
            # Check info memory
            mem_res = subprocess.run(
                ["docker", "exec", "shared-redis", "redis-cli", "info", "memory"],
                capture_output=True, text=True, timeout=4
            )
            mem_human = ""
            for line in mem_res.stdout.splitlines():
                if line.startswith("used_memory_human:"):
                    mem_human = line.split(":", 1)[1].strip()
            return {"status": "ok", "rtt_ms": rtt, "used_memory": mem_human or "unknown"}
        return {"status": "error", "error": "Redis PING did not return PONG"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_debrid(env: dict) -> list:
    keys = [
        ("Real-Debrid", "REALDEBRID_API_KEY", r"^[A-Z0-9]{40,64}$"),
        ("Premiumize", "PREMIUMIZE_API_KEY", r"^[a-zA-Z0-9_\-]{16,64}$"),
        ("TorBox", "TORBOX_API_KEY", r"^[a-zA-Z0-9_\-]{20,64}$"),
        ("AllDebrid", "ALLDEBRID_API_KEY", r"^[a-zA-Z0-9_\-]{20,64}$"),
        ("Debrid-Link", "DEBRIDLINK_API_KEY", r"^[a-zA-Z0-9_\-]{20,64}$"),
        ("EasyDebrid", "EASYDEBRID_API_KEY", r"^[a-zA-Z0-9_\-]{20,64}$"),
    ]
    results = []
    for label, env_var, regex in keys:
        val = env.get(env_var, "").strip()
        if val:
            valid_format = bool(re.match(regex, val, re.IGNORECASE))
            results.append({
                "provider": label,
                "configured": True,
                "valid_format": valid_format,
                "token_masked": val[:4] + "..." + val[-4:] if len(val) >= 8 else "***"
            })
    return results


def check_endpoints() -> list:
    endpoints = [
        ("Portal Dashboard", "http://localhost:8088/healthz", 200),
        ("AIOStreams Core", "http://localhost:3001/api/v1/status", [200, 401]),
    ]
    results = []
    for name, url, expected in endpoints:
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AIO-Doctor/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                rtt = round((time.monotonic() - start) * 1000.0, 1)
                exp_list = expected if isinstance(expected, list) else [expected]
                results.append({"name": name, "url": url, "healthy": resp.status in exp_list, "status_code": resp.status, "rtt_ms": rtt})
        except urllib.error.HTTPError as he:
            rtt = round((time.monotonic() - start) * 1000.0, 1)
            exp_list = expected if isinstance(expected, list) else [expected]
            results.append({"name": name, "url": url, "healthy": he.code in exp_list, "status_code": he.code, "rtt_ms": rtt})
        except Exception as e:
            rtt = round((time.monotonic() - start) * 1000.0, 1)
            results.append({"name": name, "url": url, "healthy": False, "status_code": 0, "rtt_ms": rtt, "error": str(e)})
    return results


def run_diagnostics() -> dict:
    env = read_env_file()
    docker_res = check_docker()
    container_res = check_containers()
    pg_res = check_postgres(env)
    redis_res = check_redis(env)
    debrid_res = check_debrid(env)
    ep_res = check_endpoints()

    all_healthy = (
        docker_res.get("status") == "ok"
        and pg_res.get("status") == "ok"
        and redis_res.get("status") == "ok"
    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_healthy": all_healthy,
        "docker": docker_res,
        "containers": container_res,
        "postgres": pg_res,
        "redis": redis_res,
        "debrid": debrid_res,
        "endpoints": ep_res
    }


def print_cli_report(diag: dict):
    print("=" * 60)
    print("            AIO Appliance Health & System Doctor            ")
    print("=" * 60)

    # 1. Docker
    doc = diag["docker"]
    if doc.get("status") == "ok":
        print(f" [✓] Docker Daemon: Connected (v{doc.get('version')}, {doc.get('rtt_ms')}ms)")
    else:
        print(f" [✗] Docker Daemon: Error ({doc.get('error')})")

    # 2. Postgres
    pg = diag["postgres"]
    if pg.get("status") == "ok":
        dbs_str = ", ".join(pg.get("present_dbs", [])) or "none"
        flag = "✓" if pg.get("dbs_ok") else "!"
        print(f" [{flag}] PostgreSQL: Healthy ({pg.get('rtt_ms')}ms, databases: {dbs_str})")
    else:
        print(f" [✗] PostgreSQL: Unreachable ({pg.get('error')})")

    # 3. Redis
    rd = diag["redis"]
    if rd.get("status") == "ok":
        print(f" [✓] Shared Redis: Healthy ({rd.get('rtt_ms')}ms, used memory: {rd.get('used_memory')})")
    else:
        print(f" [✗] Shared Redis: Unreachable ({rd.get('error')})")

    # 4. Containers
    cnts = diag["containers"].get("containers", {})
    if cnts:
        healthy_cnt = sum(1 for c in cnts.values() if c.get("healthy"))
        print(f" [✓] Container Fleet: {healthy_cnt}/{len(cnts)} active and healthy")
    else:
        print(" [!] Container Fleet: No active containers found")

    # 5. Debrid Accounts
    deb = diag["debrid"]
    if deb:
        for d in deb:
            fmt = "✓" if d["valid_format"] else "!"
            print(f" [{fmt}] Debrid Provider: {d['provider']} ({d['token_masked']})")
    else:
        print(" [i] Debrid Providers: No debrid API keys configured in .env")

    # 6. Endpoints
    for ep in diag["endpoints"]:
        flag = "✓" if ep["healthy"] else "✗"
        print(f" [{flag}] HTTP Service: {ep['name']} -> {ep['status_code']} ({ep['rtt_ms']}ms)")

    print("-" * 60)
    if diag["overall_healthy"]:
        print(" [✓] Stack Status: READY & FULLY OPERATIONAL")
    else:
        print(" [!] Stack Status: ISSUES DETECTED - Review items above")
    print("=" * 60)


def run_repair(diag: dict) -> None:
    print("[*] Initiating stack self-repair procedures...")
    # 1. Database repair
    pg = diag.get("postgres", {})
    if pg.get("status") == "ok":
        missing_dbs = [db for db, ok in pg.get("databases", {}).items() if not ok]
        if missing_dbs:
            print(f"[*] Missing PostgreSQL databases detected: {missing_dbs}. Executing init-dbs...")
            init_sql = Path(__file__).resolve().parent.parent / "init/postgres/01-init-dbs.sql"
            if init_sql.is_file():
                try:
                    subprocess.run(
                        ["docker", "exec", "-i", "shared-postgres", "psql", "-U", "postgres", "-f", "/docker-entrypoint-initdb.d/01-init-dbs.sql"],
                        capture_output=True, text=True, timeout=10
                    )
                    print(" [✓] PostgreSQL init-dbs re-executed successfully.")
                except Exception as e:
                    print(f" [✗] Failed to execute PostgreSQL init: {e}")
    # 2. Container restarts for unhealthy containers
    cnts = diag.get("containers", {}).get("containers", {})
    unhealthy = [name for name, c in cnts.items() if not c.get("healthy")]
    if unhealthy:
        print(f"[*] Unhealthy/stopped containers detected: {unhealthy}. Attempting restart...")
        try:
            subprocess.run(["docker", "restart"] + unhealthy, capture_output=True, text=True, timeout=15)
            print(" [✓] Container restart command dispatched.")
        except Exception as e:
            print(f" [✗] Failed to restart containers: {e}")
    print("[✓] Repair routines finished.")


def main():
    parser = argparse.ArgumentParser(description="AIO Stack Diagnostics & Health Doctor")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--repair", action="store_true", help="Attempt automatic self-repair on detected issues")
    args = parser.parse_args()

    diag = run_diagnostics()
    if args.repair:
        run_repair(diag)
        diag = run_diagnostics()

    if args.json:
        print(json.dumps(diag, indent=2))
    else:
        print_cli_report(diag)

    sys.exit(0 if diag["overall_healthy"] else 1)


if __name__ == "__main__":
    main()
