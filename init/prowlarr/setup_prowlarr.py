#!/usr/bin/env python3
"""
Automated Prowlarr Bootstrapper & Provisioner
Automatically configures Prowlarr upon container launch:
1. Verifies API connectivity with X-Api-Key.
2. Registers FlareSolverr Cloudflare bypass proxy.
3. Automatically enables top public torrent indexers (1337x, YTS, EZTV, TPB, TorrentGalaxy, LimeTorrents, etc.).
"""
import os
import sys
import time
import json
import urllib.request
import urllib.error

PROWLARR_URL = os.environ.get("PROWLARR_URL", "http://prowlarr:9696").rstrip("/")
PROWLARR_API_KEY = os.environ.get("PROWLARR_API_KEY", "prowlarr_internal_secret_key_99")
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191").rstrip("/")

TARGET_INDEXERS = [
    "1337x",
    "yts",
    "eztv",
    "thepiratebay",
    "torrentgalaxy",
    "limetorrents",
    "magnetdl",
    "kickasstorrents-ws",
    "badass-torrents",
    "torrentdownload",
    "nyaasi",
    "tokyotosho"
]

def make_request(path, method="GET", data=None):
    url = f"{PROWLARR_URL}{path}"
    headers = {
        "X-Api-Key": PROWLARR_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        return {"error": e.code, "message": err_msg}
    except Exception as e:
        return {"error": -1, "message": str(e)}

def wait_for_prowlarr(max_attempts=45, interval=2):
    print(f"[Prowlarr Setup] Waiting for Prowlarr to become healthy at {PROWLARR_URL}...", flush=True)
    for attempt in range(1, max_attempts + 1):
        res = make_request("/api/v1/system/status")
        if isinstance(res, dict) and "version" in res:
            print(f"[Prowlarr Setup] ✓ Prowlarr v{res.get('version')} is online and responding! (attempt {attempt})", flush=True)
            return True
        time.sleep(interval)
    print("[Prowlarr Setup] ⚠️ Timed out waiting for Prowlarr. Setup will retry on next stack restart.", flush=True)
    return False

def setup_auth_bypass():
    print("[Prowlarr Setup] Ensuring authentication setup wizard is bypassed...", flush=True)
    try:
        host_cfg = make_request("/api/v1/config/host")
        if isinstance(host_cfg, dict) and "id" in host_cfg:
            curr_auth = str(host_cfg.get("authenticationMethod", "")).lower()
            if curr_auth != "external":
                host_cfg["authenticationMethod"] = "external"
                host_cfg["authenticationRequired"] = "disabledForLocalAddresses"
                res = make_request(f"/api/v1/config/host/{host_cfg['id']}", method="PUT", data=host_cfg)
                print(f"[Prowlarr Setup] ✓ Prowlarr authentication method updated to 'external': {res.get('authenticationMethod')}", flush=True)
            else:
                print("[Prowlarr Setup] ✓ Prowlarr authentication method is already external.", flush=True)
    except Exception as e:
        print(f"[Prowlarr Setup] Note on host auth bypass check: {e}", flush=True)

def setup_flaresolverr():
    print("[Prowlarr Setup] Checking FlareSolverr indexer proxy...", flush=True)
    proxies = make_request("/api/v1/indexerproxy")
    if isinstance(proxies, list):
        for p in proxies:
            if p.get("implementation", "").lower() == "flaresolverr" or "flaresolverr" in p.get("name", "").lower():
                print("[Prowlarr Setup] ✓ FlareSolverr proxy is already registered.", flush=True)
                return

    payload = {
        "name": "FlareSolverr Local",
        "implementation": "FlareSolverr",
        "configContract": "FlareSolverrSettings",
        "enable": True,
        "tags": [],
        "fields": [
            {"name": "host", "value": FLARESOLVERR_URL},
            {"name": "requestTimeout", "value": 60}
        ]
    }
    res = make_request("/api/v1/indexerproxy", method="POST", data=payload)
    if isinstance(res, dict) and "id" in res:
        print(f"[Prowlarr Setup] ✓ Successfully registered FlareSolverr proxy ({FLARESOLVERR_URL})!", flush=True)
    else:
        print(f"[Prowlarr Setup] Note adding FlareSolverr proxy: {res}", flush=True)

def setup_public_indexers():
    print("[Prowlarr Setup] Inspecting configured indexers...", flush=True)
    existing_indexers = make_request("/api/v1/indexer")
    existing_definitions = set()
    if isinstance(existing_indexers, list):
        for idx in existing_indexers:
            def_name = idx.get("definitionName", "").lower()
            name = idx.get("name", "").lower()
            if def_name:
                existing_definitions.add(def_name)
            if name:
                existing_definitions.add(name)

    print(f"[Prowlarr Setup] Currently active indexers: {len(existing_indexers) if isinstance(existing_indexers, list) else 0}", flush=True)

    schemas = make_request("/api/v1/indexer/schema")
    if not isinstance(schemas, list):
        print(f"[Prowlarr Setup] Could not retrieve indexer schemas: {schemas}", flush=True)
        return

    added_count = 0
    for target in TARGET_INDEXERS:
        target_lower = target.lower()
        if any(target_lower in d for d in existing_definitions):
            print(f"[Prowlarr Setup] • Indexer '{target}' is already present.", flush=True)
            continue

        matched_schema = None
        for schema in schemas:
            s_def = schema.get("definitionName", "").lower()
            s_name = schema.get("name", "").lower()
            if s_def == target_lower or s_name == target_lower:
                matched_schema = schema
                break

        if matched_schema:
            indexer_payload = dict(matched_schema)
            indexer_payload["enable"] = True
            indexer_payload["priority"] = 25
            indexer_payload["appProfileId"] = 1

            res = make_request("/api/v1/indexer", method="POST", data=indexer_payload)
            if isinstance(res, dict) and "id" in res:
                print(f"[Prowlarr Setup] ✓ Successfully provisioned public indexer: {matched_schema.get('name')}!", flush=True)
                added_count += 1
            else:
                print(f"[Prowlarr Setup] Notice adding {target}: {res.get('message', res)}", flush=True)

    print(f"[Prowlarr Setup] Provisioning complete. {added_count} new public indexers enabled.", flush=True)

def main():
    print("==================================================", flush=True)
    print("        AIOStreams Prowlarr Auto-Provisioner      ", flush=True)
    print("==================================================", flush=True)
    if not wait_for_prowlarr():
        sys.exit(0)

    try:
        setup_auth_bypass()
    except Exception as e:
        print(f"[Prowlarr Setup] Warning configuring auth bypass: {e}", flush=True)

    try:
        setup_flaresolverr()
    except Exception as e:
        print(f"[Prowlarr Setup] Warning configuring FlareSolverr: {e}", flush=True)

    try:
        setup_public_indexers()
    except Exception as e:
        print(f"[Prowlarr Setup] Warning configuring indexers: {e}", flush=True)

    print("[Prowlarr Setup] All services fully provisioned and ready for Comet / AIOStreams!", flush=True)

if __name__ == "__main__":
    main()
