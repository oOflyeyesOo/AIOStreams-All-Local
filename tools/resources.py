#!/usr/bin/env python3
"""
AIO Local Stack Live Resource Monitor
=====================================
Monitors real-time CPU % and RAM usage across all application containers in the
AIOStreams self-hosted stack. Formats output cleanly for CLI dashboards
and supplies structured JSON metrics for the Appliance Setup Portal.
"""

import argparse
import os
import json
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


AIO_CONTAINERS = {
    "aiostreams", "comet", "sootio", "zilean", "prowlarr",
    "flaresolverr", "stremthru", "infinidysk", "cloudflared",
    "aio-tunnel", "anime-kitsu", "aiometadata", "postersplus", "stremio-subsense",
    "nuvio-web", "stremio-web", "slicksync", "shared-redis", "shared-postgres",
    "aio-portal", "stack-bootstrap", "init-configs", "init-postgres", "aio-stack"
}


def parse_bytes(val_str: str) -> float:
    """Parse docker memory string like '279.3MiB' or '1.85GiB' or '512kB' to megabytes (MB)."""
    val_str = val_str.strip()
    match = re.match(r"^([\d.]+)\s*([a-zA-Z]+)$", val_str)
    if not match:
        return 0.0
    num = float(match.group(1))
    unit = match.group(2).lower()

    if "gib" in unit or "gb" in unit:
        return num * 1024.0
    elif "mib" in unit or "mb" in unit:
        return num
    elif "kib" in unit or "kb" in unit:
        return num / 1024.0
    elif "b" in unit:
        return num / (1024.0 * 1024.0)
    return num


def get_stack_resources(filter_aio: bool = True) -> dict:
    """Query docker stats and parse all containers into structured metric objects."""
    cmd = [
        "docker", "stats", "--no-stream",
        "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.PIDs}}"
    ]
    project = os.environ.get("AIO_PROJECT_NAME") if filter_aio else None
    try:
        if project:
            listing = subprocess.run(["docker", "ps", "-q", "--filter",
                                      f"label=com.docker.compose.project={project}"],
                                     capture_output=True, text=True, check=True, timeout=12)
            ids = listing.stdout.split()
            if not ids:
                return {"success": True, "containers": [], "container_count": 0,
                        "total_mem_mb": 0, "total_mem_gb": 0, "total_cpu_percent": 0,
                        "host_limit_gb": 0, "host_mem_percent": 0}
            cmd.extend(ids)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if res.returncode != 0:
            return {
                "success": False,
                "error": res.stderr.strip() or "Docker stats command failed",
                "containers": []
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "containers": []
        }

    containers = []
    total_mem_mb = 0.0
    total_cpu_perc = 0.0
    host_limit_mb = 0.0
    try:
        memory = subprocess.run(["docker", "info", "--format", "{{.MemTotal}}"],
                                capture_output=True, text=True, check=True, timeout=12)
        host_limit_mb = int(memory.stdout.strip()) / (1024 * 1024)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    lines = res.stdout.strip().splitlines()
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        c_name = parts[0].strip()
        if filter_aio and not project and c_name not in AIO_CONTAINERS and not c_name.startswith("aio-"):
            continue

        cpu_raw = parts[1].strip()
        mem_raw = parts[2].strip()
        mem_perc_raw = parts[3].strip()
        net_raw = parts[4].strip()
        pids_raw = parts[5].strip() if len(parts) > 5 else "0"

        cpu_val = 0.0
        try:
            cpu_val = float(cpu_raw.replace("%", "").strip())
        except ValueError:
            pass

        mem_perc_val = 0.0
        try:
            mem_perc_val = float(mem_perc_raw.replace("%", "").strip())
        except ValueError:
            pass

        used_mb = 0.0
        limit_mb = 0.0
        if "/" in mem_raw:
            used_str, limit_str = mem_raw.split("/", 1)
            used_mb = parse_bytes(used_str)
            limit_mb = parse_bytes(limit_str)
        else:
            used_mb = parse_bytes(mem_raw)

        pids = 0
        try:
            pids = int(pids_raw)
        except ValueError:
            pass

        total_mem_mb += used_mb
        total_cpu_perc += cpu_val

        containers.append({
            "name": c_name,
            "cpu_percent": round(cpu_val, 2),
            "mem_used_mb": round(used_mb, 2),
            "mem_limit_mb": round(limit_mb, 2),
            "mem_percent": round(mem_perc_val, 2),
            "mem_raw": mem_raw,
            "net_io": net_raw,
            "pids": pids
        })

    # Sort descending by memory usage
    containers.sort(key=lambda c: c["mem_used_mb"], reverse=True)

    total_mem_gb = round(total_mem_mb / 1024.0, 2)
    host_limit_gb = round(host_limit_mb / 1024.0, 2)
    host_mem_perc = round((total_mem_mb / host_limit_mb) * 100.0, 2) if host_limit_mb > 0 else 0.0

    return {
        "success": True,
        "container_count": len(containers),
        "total_mem_mb": round(total_mem_mb, 2),
        "total_mem_gb": total_mem_gb,
        "total_cpu_percent": round(total_cpu_perc, 2),
        "host_limit_gb": host_limit_gb,
        "host_mem_percent": host_mem_perc,
        "containers": containers
    }


def main():
    parser = argparse.ArgumentParser(description="AIO Local Stack Live Resource Monitor")
    parser.add_argument("--all", action="store_true", help="Include non-stack containers running on host")
    parser.add_argument("--json", action="store_true", help="Output stats in JSON format")
    args = parser.parse_args()

    stats = get_stack_resources(filter_aio=not args.all)

    if args.json:
        print(json.dumps(stats, indent=2))
        return

    if not stats.get("success"):
        print(f"[-] Unable to query docker stats: {stats.get('error')}")
        sys.exit(1)

    print("\n=========================================================================================")
    print("  AIO Local Self-Hosted Stack — Live Container Resource Monitor")
    print("=========================================================================================")
    header = f"{'CONTAINER NAME':<26} {'CPU %':<10} {'RAM USAGE / LIMIT':<24} {'RAM %':<10} {'PIDS':<6}"
    print(header)
    print("-" * 89)

    for c in stats["containers"]:
        print(f"{c['name']:<26} {c['cpu_percent']:>6.2f}%   {c['mem_raw']:<24} {c['mem_percent']:>6.2f}%   {c['pids']:>4}")

    print("=" * 89)
    print(f" TOTAL STACK RAM : {stats['total_mem_mb']:.1f} MiB ({stats['total_mem_gb']:.2f} GiB / {stats['host_limit_gb']:.1f} GiB Host -> {stats['host_mem_percent']:.1f}%)")
    print(f" TOTAL STACK CPU : {stats['total_cpu_percent']:.2f}% across {stats['container_count']} active containers")
    print("=========================================================================================\n")


if __name__ == "__main__":
    main()
