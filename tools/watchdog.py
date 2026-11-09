#!/usr/bin/env python3
"""
AIO Local Stack Self-Healing Watchdog Daemon
===========================================
Monitors health endpoints across all services in the AIOStreams self-hosted stack.
When an unresponsive or hung service is detected (exceeding consecutive failure thresholds),
the watchdog automatically triggers a container restart and dispatches rich status alerts
via Discord Webhook (if DISCORD_WEBHOOK_URL is configured).

Can be executed as:
  • Single-pass probe:  python tools/watchdog.py --check-once
  • Background daemon:   python tools/watchdog.py --daemon --interval 60
  • Telemetry provider: Imported by portal_server.py for live dashboard health stats
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def is_running_in_docker() -> bool:
    """Detect whether this process is running inside a Docker container."""
    return Path("/.dockerenv").is_file() or os.environ.get("IN_DOCKER") == "1"


def get_service_endpoints() -> list:
    """Return endpoint probe configurations for all stack services."""
    in_docker = is_running_in_docker()
    
    # Internal docker DNS host:port vs Host loopback 127.0.0.1:port
    if in_docker:
        return [
            {"service": "aiostreams", "container": "aiostreams", "url": "http://aiostreams:3000/manifest.json", "expected_code": 200, "critical": True},
            {"service": "aiometadata", "container": "aiometadata", "url": "http://aiometadata:4005/manifest.json", "expected_code": [200, 404], "critical": True},
            {"service": "comet", "container": "comet", "url": "http://comet:8000/", "expected_code": 200, "critical": True},
            {"service": "mediafusion", "container": "mediafusion", "url": "http://mediafusion:8000/health", "expected_code": 200, "critical": False},
            {"service": "subsense", "container": "stremio-subsense", "url": "http://subsense:3100/", "expected_code": 200, "critical": False},
            {"service": "stremio-web", "container": "stremio-web", "url": "http://stremio-web:8080/", "expected_code": 200, "critical": True},
            {"service": "infinidysk", "container": "infinidysk", "url": "http://infinidysk:3000/", "expected_code": 200, "critical": False},
            {"service": "slicksync", "container": "slicksync", "url": "http://slicksync:3000/", "expected_code": 200, "critical": False},
            {"service": "anime-kitsu", "container": "anime-kitsu", "url": "http://anime-kitsu:7000/", "expected_code": 200, "critical": False},
            {"service": "debrid-search", "container": "stremio-debrid-search", "url": "http://debrid-search:3011/", "expected_code": 200, "critical": False},
            {"service": "mediaflow", "container": "mediaflow", "url": "http://mediaflow:8888/", "expected_code": 200, "critical": False},
            {"service": "stremthru", "container": "stremthru", "url": "http://stremthru:8080/v0/health", "expected_code": 200, "critical": False},
            {"service": "zilean", "container": "zilean", "url": "http://zilean:8181/dmm/filtered", "expected_code": 200, "critical": False},
            {"service": "prowlarr", "container": "prowlarr", "url": "http://prowlarr:9696/ping", "expected_code": 200, "critical": False},
        ]
    else:
        return [
            {"service": "aiostreams", "container": "aiostreams", "url": "http://127.0.0.1:3001/manifest.json", "expected_code": 200, "critical": True},
            {"service": "aiometadata", "container": "aiometadata", "url": "http://127.0.0.1:4005/manifest.json", "expected_code": [200, 404], "critical": True},
            {"service": "comet", "container": "comet", "url": "http://127.0.0.1:8000/", "expected_code": 200, "critical": True},
            {"service": "mediafusion", "container": "mediafusion", "url": "http://127.0.0.1:8001/health", "expected_code": 200, "critical": False},
            {"service": "subsense", "container": "stremio-subsense", "url": "http://127.0.0.1:3100/", "expected_code": 200, "critical": False},
            {"service": "stremio-web", "container": "stremio-web", "url": "http://127.0.0.1:8082/", "expected_code": 200, "critical": True},
            {"service": "infinidysk", "container": "infinidysk", "url": "http://127.0.0.1:3005/", "expected_code": 200, "critical": False},
            {"service": "slicksync", "container": "slicksync", "url": "http://127.0.0.1:8086/", "expected_code": 200, "critical": False},
            {"service": "anime-kitsu", "container": "anime-kitsu", "url": "http://127.0.0.1:7005/", "expected_code": 200, "critical": False},
            {"service": "debrid-search", "container": "stremio-debrid-search", "url": "http://127.0.0.1:3011/", "expected_code": 200, "critical": False},
            {"service": "mediaflow", "container": "mediaflow", "url": "http://127.0.0.1:8888/", "expected_code": 200, "critical": False},
            {"service": "stremthru", "container": "stremthru", "url": "http://127.0.0.1:8080/v0/health", "expected_code": 200, "critical": False},
            {"service": "zilean", "container": "zilean", "url": "http://127.0.0.1:8181/dmm/filtered", "expected_code": 200, "critical": False},
            {"service": "prowlarr", "container": "prowlarr", "url": "http://127.0.0.1:9696/ping", "expected_code": 200, "critical": False},
        ]


# State tracking across checks
FAILURE_COUNTS = {}
LAST_RESTART = {}
PROBE_HISTORY = []
MAX_HISTORY = 30
MEMORY_FAILURES = {}
LAST_MEMORY_RESTART = {}
DISCORD_ALERT_HISTORY = []
MAX_ALERTS_PER_WINDOW = 3
ALERT_WINDOW_SECONDS = 60
THROTTLED_ALERTS_COUNT = 0
LAST_ANIME_DELTA_CHECK = 0


def get_webhook_url() -> str:
    """Read DISCORD_WEBHOOK_URL from environment or .env file."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if url:
        return url
    env_file = Path.cwd() / ".env"
    if not env_file.is_file():
        script_dir = Path(__file__).resolve().parent.parent
        env_file = script_dir / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DISCORD_WEBHOOK_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def send_discord_alert(title: str, description: str, color: int = 0x3498DB, fields: list = None) -> bool:
    """Send an embed notification to Discord Webhook with storm throttling."""
    global THROTTLED_ALERTS_COUNT
    webhook_url = get_webhook_url()
    if not webhook_url:
        return False

    now = time.monotonic()
    # Prune alerts older than the sliding window
    while DISCORD_ALERT_HISTORY and (now - DISCORD_ALERT_HISTORY[0]) > ALERT_WINDOW_SECONDS:
        DISCORD_ALERT_HISTORY.pop(0)

    if len(DISCORD_ALERT_HISTORY) >= MAX_ALERTS_PER_WINDOW:
        THROTTLED_ALERTS_COUNT += 1
        return False

    try:
        fields_list = list(fields) if fields else []
        if THROTTLED_ALERTS_COUNT > 0:
            fields_list.append({
                "name": "Alert Storm Throttling",
                "value": f"{THROTTLED_ALERTS_COUNT} intermediate alert(s) were suppressed during rapid-fire activity.",
                "inline": False
            })
            THROTTLED_ALERTS_COUNT = 0

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "AIO Local Watchdog • Self-Healing System"}
        }
        if fields_list:
            embed["fields"] = fields_list
        payload = {"embeds": [embed]}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AIO-Watchdog/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 204):
                DISCORD_ALERT_HISTORY.append(now)
                return True
            return False
    except Exception as e:
        print(f"  [!] Failed to deliver Discord webhook: {e}", file=sys.stderr)
        return False


def probe_single_endpoint(endpoint: dict, timeout: float = 3.5) -> dict:
    """Probe a single service endpoint and return latency and health status."""
    url = endpoint["url"]
    expected = endpoint["expected_code"]
    if isinstance(expected, int):
        expected = [expected]

    start_time = time.monotonic()
    status_code = 0
    error_msg = ""
    healthy = False

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AIO-Watchdog/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            healthy = status_code in expected
    except urllib.error.HTTPError as he:
        status_code = he.code
        healthy = status_code in expected
        if not healthy:
            error_msg = f"HTTP {he.code}"
    except urllib.error.URLError as ue:
        error_msg = str(ue.reason) if hasattr(ue, "reason") else str(ue)
    except Exception as e:
        error_msg = str(e)

    elapsed_ms = round((time.monotonic() - start_time) * 1000.0, 1)

    return {
        "service": endpoint["service"],
        "container": endpoint["container"],
        "url": url,
        "healthy": healthy,
        "status_code": status_code,
        "latency_ms": elapsed_ms,
        "error": error_msg,
        "critical": endpoint.get("critical", False)
    }


def check_memory_pressure(threshold_percent: float = 95.0, auto_restart: bool = False, cooldown_sec: int = 180) -> list:
    """Check running containers for sustained memory pressure and optionally restart."""
    alerts = []
    now = time.monotonic()
    try:
        res = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}	{{.MemPerc}}"],
            capture_output=True, text=True, timeout=10
        )
        if res.returncode != 0:
            return []
        for line in res.stdout.strip().splitlines():
            parts = line.split("	")
            if len(parts) < 2:
                continue
            name, perc_str = parts[0].strip(), parts[1].strip().rstrip("%")
            try:
                perc = float(perc_str)
            except ValueError:
                continue
            if perc >= threshold_percent:
                hits = MEMORY_FAILURES.get(name, 0) + 1
                MEMORY_FAILURES[name] = hits
                entry = {"container": name, "mem_percent": perc, "consecutive_hits": hits}
                if auto_restart and hits >= 3:
                    last_r = LAST_MEMORY_RESTART.get(name, 0)
                    if now - last_r >= cooldown_sec:
                        LAST_MEMORY_RESTART[name] = now
                        MEMORY_FAILURES[name] = 0
                        restarted = restart_container(name)
                        if restarted:
                            entry["restarted"] = True
                            send_discord_alert(
                                title=f"⚠️ AIO Watchdog: Memory Limit Restart ({name})",
                                description=f"Container `{name}` sustained {perc}% memory usage for {hits} consecutive checks.\nAutomatic restart executed to relieve memory pressure.",
                                color=0xE74C3C,
                                fields=[
                                    {"name": "Container", "value": name, "inline": True},
                                    {"name": "RAM Usage", "value": f"{perc}%", "inline": True}
                                ]
                            )
                alerts.append(entry)
            else:
                MEMORY_FAILURES[name] = 0
    except Exception:
        pass
    return alerts


def check_prowlarr_indexers() -> dict:
    """Probe Prowlarr indexer inventory and identify degraded or rate-limited indexers."""
    in_docker = is_running_in_docker()
    prowlarr_base = "http://prowlarr:9696" if in_docker else "http://127.0.0.1:9696"
    api_key = os.environ.get("PROWLARR_API_KEY", "prowlarr_internal_secret_key_99")
    headers = {"X-Api-Key": api_key, "User-Agent": "AIO-Watchdog/2.0"}

    try:
        req_idx = urllib.request.Request(f"{prowlarr_base}/api/v1/indexer", headers=headers)
        with urllib.request.urlopen(req_idx, timeout=3.5) as r:
            indexers = json.loads(r.read().decode("utf-8"))
            id_to_name = {idx["id"]: idx.get("name", f"Indexer #{idx['id']}") for idx in indexers if isinstance(idx, dict) and "id" in idx}

        req_st = urllib.request.Request(f"{prowlarr_base}/api/v1/indexerstatus", headers=headers)
        with urllib.request.urlopen(req_st, timeout=3.5) as r:
            statuses = json.loads(r.read().decode("utf-8"))
            degraded = []
            for s in statuses:
                if isinstance(s, dict) and s.get("disabledTill"):
                    degraded.append({
                        "id": s.get("indexerId"),
                        "name": id_to_name.get(s.get("indexerId"), f"Indexer #{s.get('indexerId')}"),
                        "disabled_till": s.get("disabledTill")
                    })
            return {
                "total_indexers": len(id_to_name),
                "healthy_indexers": len(id_to_name) - len(degraded),
                "degraded_indexers": degraded
            }
    except Exception:
        return {"total_indexers": 0, "healthy_indexers": 0, "degraded_indexers": []}


def get_zilean_stats() -> dict:
    """Probe Zilean DMM hash search engine and report latency and status."""
    in_docker = is_running_in_docker()
    zilean_base = "http://zilean:8181" if in_docker else "http://127.0.0.1:8181"
    start = time.monotonic()
    try:
        req = urllib.request.Request(f"{zilean_base}/dmm/filtered?query=ping", headers={"User-Agent": "AIO-Watchdog/2.0"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            elapsed = round((time.monotonic() - start) * 1000.0, 1)
            return {
                "healthy": resp.status == 200,
                "status_code": resp.status,
                "latency_ms": elapsed,
                "engine": "DMM Hash Search (Active)"
            }
    except Exception as e:
        elapsed = round((time.monotonic() - start) * 1000.0, 1)
        return {
            "healthy": False,
            "status_code": 0,
            "latency_ms": elapsed,
            "error": str(e),
            "engine": "DMM Hash Search"
        }


def check_scheduled_backup(keep_last: int = 5) -> dict:
    """Check if automated daily/weekly backup is due and trigger it."""
    schedule = os.environ.get("BACKUP_SCHEDULE", "").strip().lower()
    if not schedule:
        try:
            env_file = Path.cwd() / ".env"
            if not env_file.is_file():
                env_file = Path(__file__).resolve().parent.parent / ".env"
            if env_file.is_file():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("BACKUP_SCHEDULE="):
                        schedule = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
        except Exception:
            pass
    schedule = schedule or "daily"
    if schedule == "off":
        return {"status": "disabled"}

    try:
        import tools.backup as stack_backup
    except ImportError:
        return {"status": "unavailable"}

    project_root = Path.cwd()
    if not (project_root / "compose.manager.yml").is_file():
        project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "backups"
    output_dir.mkdir(parents=True, exist_ok=True)

    telemetry = stack_backup.get_backup_telemetry(output_dir, project_root)
    latest_str = telemetry.get("latest")
    now_utc = datetime.now(timezone.utc)
    is_due = False

    if not latest_str or telemetry.get("count", 0) == 0:
        is_due = True
    else:
        try:
            latest_dt = datetime.fromisoformat(latest_str)
            age_hours = (now_utc - latest_dt).total_seconds() / 3600.0
            if schedule == "daily" and age_hours >= 24.0:
                is_due = True
            elif schedule == "weekly" and age_hours >= 168.0:
                is_due = True
        except Exception:
            is_due = True

    if is_due:
        print(f"  [i] Automated backup is due (schedule={schedule}). Creating backup...", flush=True)
        res = stack_backup.create_backup(output_dir=output_dir, project_root=project_root, keep_last=keep_last)
        if res.get("success"):
            send_discord_alert(
                title="💾 AIO Automated Backup Created",
                description=f"Automated scheduled backup completed successfully (`{schedule}`).\nArchive: `{res.get('archive')}` ({res.get('size_mb')} MB)",
                color=0x3498DB
            )
        return res
    return {"status": "up_to_date", "latest": latest_str}


def refresh_anime_ids_delta() -> dict:
    """Periodically refresh anime ID mappings from community repositories."""
    global LAST_ANIME_DELTA_CHECK
    now = time.monotonic()
    if LAST_ANIME_DELTA_CHECK != 0 and (now - LAST_ANIME_DELTA_CHECK) < 86400:
        return {"status": "skipped_recent"}
    LAST_ANIME_DELTA_CHECK = now

    project_root = Path.cwd()
    if not (project_root / "compose.manager.yml").is_file():
        project_root = Path(__file__).resolve().parent.parent
    db_path = project_root / "data" / "postersplus" / "anime_ids.db"
    if not db_path.is_file():
        return {"status": "no_db"}

    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-mini.json",
            headers={"User-Agent": "AIO-Watchdog/2.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            inserted = 0
            for item in data:
                mal_id = item.get("mal_id")
                kitsu_id = item.get("kitsu_id")
                anilist_id = item.get("anilist_id")
                if mal_id and (kitsu_id or anilist_id):
                    cur.execute(
                        "INSERT OR IGNORE INTO anime_mal_map (mal_id, kitsu_id, anilist_id) VALUES (?, ?, ?)",
                        (mal_id, kitsu_id, anilist_id)
                    )
                    inserted += cur.rowcount
            conn.commit()
            conn.close()
            return {"status": "refreshed", "new_mappings": inserted}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def restart_container(container_name: str) -> bool:
    """Trigger a docker container restart."""
    try:
        res = subprocess.run(["docker", "restart", container_name],
                             capture_output=True, text=True, timeout=30)
        return res.returncode == 0
    except Exception as e:
        print(f"  [!] Error restarting container {container_name}: {e}", file=sys.stderr)
        return False


def probe_all_services(auto_restart: bool = False, max_failures: int = 3, cooldown_sec: int = 120, check_memory: bool = True, mem_threshold: float = 95.0) -> dict:
    """Run a full check pass across all service endpoints and handle self-healing."""
    endpoints = get_service_endpoints()
    results = []
    total_healthy = 0
    restarts_triggered = []
    recovered = []
    now = time.monotonic()

    for ep in endpoints:
        probe = probe_single_endpoint(ep)
        svc = probe["service"]
        cnt = probe["container"]

        if probe["healthy"]:
            total_healthy += 1
            if FAILURE_COUNTS.get(svc, 0) >= max_failures:
                # Was previously marked failing, now recovered!
                recovered.append(svc)
                send_discord_alert(
                    title=f"✅ AIO Watchdog Recovery: {svc}",
                    description=f"Service `{svc}` ({cnt}) has recovered and is now responding normally.",
                    color=0x2ECC71,
                    fields=[
                        {"name": "Endpoint", "value": probe["url"], "inline": True},
                        {"name": "Latency", "value": f"{probe['latency_ms']} ms", "inline": True}
                    ]
                )
            FAILURE_COUNTS[svc] = 0
        else:
            failures = FAILURE_COUNTS.get(svc, 0) + 1
            FAILURE_COUNTS[svc] = failures
            probe["failures"] = failures

            if auto_restart and failures >= max_failures:
                last_r = LAST_RESTART.get(cnt, 0)
                if now - last_r >= cooldown_sec:
                    LAST_RESTART[cnt] = now
                    print(f"  [!] Triggering self-healing restart for {cnt} (failed {failures} checks)...", flush=True)
                    restarted = restart_container(cnt)
                    if restarted:
                        restarts_triggered.append(cnt)
                        send_discord_alert(
                            title=f"⚠️ AIO Watchdog Alert: Restart Triggered ({svc})",
                            description=f"Service `{svc}` failed {failures} consecutive health probes.\nAutomatic restart executed successfully.",
                            color=0xE67E22,
                            fields=[
                                {"name": "Container", "value": cnt, "inline": True},
                                {"name": "Error", "value": probe["error"] or "Timeout", "inline": True},
                                {"name": "Consecutive Failures", "value": str(failures), "inline": True}
                            ]
                        )
                else:
                    remaining = int(cooldown_sec - (now - last_r))
                    probe["cooldown_remaining_sec"] = remaining

        results.append(probe)

    mem_alerts = check_memory_pressure(threshold_percent=mem_threshold, auto_restart=auto_restart) if check_memory else []
    prowlarr_idx = check_prowlarr_indexers()
    zilean_stats = get_zilean_stats()

    timestamp = datetime.now(timezone.utc).isoformat()
    summary = {
        "timestamp": timestamp,
        "total_services": len(endpoints),
        "healthy_count": total_healthy,
        "unhealthy_count": len(endpoints) - total_healthy,
        "overall_status": "healthy" if total_healthy == len(endpoints) else "degraded",
        "restarts_triggered": restarts_triggered,
        "recovered": recovered,
        "services": results,
        "memory_alerts": mem_alerts,
        "indexer_health": prowlarr_idx,
        "zilean_stats": zilean_stats
    }

    PROBE_HISTORY.append({
        "timestamp": timestamp,
        "healthy_count": total_healthy,
        "total_services": len(endpoints),
        "restarts_triggered": len(restarts_triggered)
    })
    if len(PROBE_HISTORY) > MAX_HISTORY:
        PROBE_HISTORY.pop(0)

    return summary


def get_watchdog_telemetry() -> dict:
    """Retrieve summarized watchdog telemetry for the portal."""
    latest = PROBE_HISTORY[-1] if PROBE_HISTORY else None
    return {
        "status": "active",
        "last_probe": latest["timestamp"] if latest else None,
        "healthy_count": latest["healthy_count"] if latest else 0,
        "total_services": latest["total_services"] if latest else 0,
        "overall": "healthy" if (latest and latest["healthy_count"] == latest["total_services"]) else "degraded",
        "failure_counts": dict(FAILURE_COUNTS),
        "indexer_health": PROBE_HISTORY[-1].get("indexer_health") if PROBE_HISTORY else check_prowlarr_indexers(),
        "zilean_stats": PROBE_HISTORY[-1].get("zilean_stats") if PROBE_HISTORY else get_zilean_stats(),
        "history": list(PROBE_HISTORY)
    }


def run_daemon(interval: int = 60, max_failures: int = 3, auto_restart: bool = True):
    """Run watchdog loop indefinitely."""
    print(f"\n=========================================================================")
    print(f"  AIO Local Self-Healing Watchdog Daemon Active")
    print(f"=========================================================================")
    print(f"  Interval       : Every {interval} seconds")
    print(f"  Failure Threshold: {max_failures} consecutive checks before restart")
    print(f"  Auto-Restart   : {'Enabled' if auto_restart else 'Disabled'}")
    webhook = get_webhook_url()
    print(f"  Discord Alerts : {'Configured' if webhook else 'Not configured (set DISCORD_WEBHOOK_URL in .env)'}")
    print(f"=========================================================================\n")

    try:
        while True:
            summary = probe_all_services(auto_restart=auto_restart, max_failures=max_failures)
            status_sym = "✓" if summary["overall_status"] == "healthy" else "!"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{status_sym}] Checked {summary['total_services']} services: {summary['healthy_count']} healthy, {summary['unhealthy_count']} degraded.")
            if summary["restarts_triggered"]:
                print(f"    -> Self-healing restarted: {', '.join(summary['restarts_triggered'])}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[i] Watchdog daemon stopped by user.")


def main():
    parser = argparse.ArgumentParser(description="AIO Local Stack Self-Healing Watchdog Daemon")
    parser.add_argument("--check-once", "--probe", action="store_true", help="Run a single health probe pass and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background daemon loop")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds for daemon mode (default: 60)")
    parser.add_argument("--max-failures", type=int, default=3, help="Consecutive failures before restart (default: 3)")
    parser.add_argument("--mem-threshold", type=float, default=95.0, help="Memory percentage threshold for auto-restart (default: 95.0)")
    parser.add_argument("--no-restart", action="store_true", help="Disable automatic container restarts")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    if args.daemon:
        run_daemon(interval=args.interval, max_failures=args.max_failures, auto_restart=not args.no_restart)
    else:
        summary = probe_all_services(auto_restart=not args.no_restart, max_failures=args.max_failures)
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print("\n=========================================================================")
            print(f"  AIO Local Stack Health & Self-Healing Probe ({summary['timestamp'][:19]})")
            print("=========================================================================")
            header = f"{'SERVICE':<16} {'STATUS':<10} {'LATENCY':<12} {'HTTP':<8} {'ENDPOINT'}"
            print(header)
            print("-" * 75)
            for s in summary["services"]:
                status_str = "✓ HEALTHY" if s["healthy"] else "✗ DEGRADED"
                code_str = str(s["status_code"]) if s["status_code"] else "ERR"
                lat_str = f"{s['latency_ms']} ms"
                print(f"{s['service']:<16} {status_str:<10} {lat_str:<12} {code_str:<8} {s['url']}")
                if s["error"]:
                    print(f"    ↳ Error: {s['error']}")
            print("=" * 75)
            print(f"SUMMARY: {summary['healthy_count']} / {summary['total_services']} services operational ({summary['overall_status'].upper()})\n")


if __name__ == "__main__":
    main()
