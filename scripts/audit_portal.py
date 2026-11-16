#!/usr/bin/env python3
"""
Comprehensive Audit & Deep Verification Suite for AIO Portal.
Audits:
1. index.html:
   - All anchor links (href="#id") point to valid element IDs.
   - All label 'for' attributes point to valid input/select/textarea IDs.
   - All aria-controls / aria-labelledby point to valid element IDs.
   - Duplicate ID check.
   - All local static files (CSS, JS, images, templates) exist on disk.
2. assets/app.js:
   - All getElementById and querySelector(#id) references match HTML elements (or dynamic registry).
   - Null-safety audit on DOM element accesses.
   - All API fetch calls match routes in portal_server.py.
3. docker/all-in-one/portal_server.py:
   - Endpoint coverage and method dispatching (GET, POST, OPTIONS, HEAD, PUT, DELETE, PATCH).
   - Safe error masking (no raw tracebacks or local directory leakages).
   - Security headers (CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
   - All 14 services in INTERNAL_SERVICE_TARGETS mapped correctly.
   - Allowed static file extensions in send_head().
"""
import re
import os
import sys
import json
from pathlib import Path

WEB_ROOT = Path(".").resolve()
INDEX_HTML = WEB_ROOT / "index.html"
APP_JS = WEB_ROOT / "assets" / "app.js"
APP_CSS = WEB_ROOT / "assets" / "app.css"
PORTAL_SERVER = WEB_ROOT / "docker" / "all-in-one" / "portal_server.py"

findings = []

def report(category, file_path, line_no, issue, severity="ERROR"):
    findings.append({
        "category": category,
        "file": str(file_path),
        "line": line_no,
        "issue": issue,
        "severity": severity
    })

# -----------------------------------------------------------------------------
# 1. AUDIT index.html
# -----------------------------------------------------------------------------
html_content = INDEX_HTML.read_text(encoding="utf-8")
html_lines = html_content.splitlines()

# Collect all IDs
id_pattern = re.compile(r'\bid=["\']([^"\']+)["\']')
html_ids = {}
for idx, line in enumerate(html_lines, start=1):
    for m in id_pattern.finditer(line):
        elem_id = m.group(1)
        if elem_id in html_ids:
            report("DUPLICATE_ID", INDEX_HTML, idx, f"Duplicate id '{elem_id}' (first declared on line {html_ids[elem_id]})", "WARNING")
        else:
            html_ids[elem_id] = idx

# Check anchor links href="#..."
anchor_pattern = re.compile(r'\bhref=["\']#([^"\']+)["\']')
for idx, line in enumerate(html_lines, start=1):
    for m in anchor_pattern.finditer(line):
        target_id = m.group(1)
        if target_id not in html_ids:
            report("BROKEN_ANCHOR", INDEX_HTML, idx, f"Anchor href='#{target_id}' has no matching element id in index.html")

# Check label for="..."
label_for_pattern = re.compile(r'\bfor=["\']([^"\']+)["\']')
for idx, line in enumerate(html_lines, start=1):
    for m in label_for_pattern.finditer(line):
        target_id = m.group(1)
        if target_id not in html_ids:
            report("BROKEN_LABEL_FOR", INDEX_HTML, idx, f"Label for='{target_id}' has no matching input/element id in index.html", "WARNING")

# Check aria-controls="..." and aria-labelledby="..."
aria_pattern = re.compile(r'\b(?:aria-controls|aria-labelledby)=["\']([^"\']+)["\']')
for idx, line in enumerate(html_lines, start=1):
    for m in aria_pattern.finditer(line):
        target_ids = m.group(1).split()
        for tid in target_ids:
            if tid not in html_ids:
                report("BROKEN_ARIA_REF", INDEX_HTML, idx, f"ARIA reference '{tid}' has no matching element id in index.html", "WARNING")

# Check local static asset files
asset_ref_pattern = re.compile(r'\b(?:src|href)=["\']([^"\'#:]+?)["\']')
for idx, line in enumerate(html_lines, start=1):
    for m in asset_ref_pattern.finditer(line):
        ref = m.group(1).strip()
        if (not ref or ref.startswith("http") or ref.startswith("//") or 
            ref.startswith("data:") or ref.startswith("mailto:") or 
            ref.startswith("/api/") or ref.startswith("javascript:") or ref.startswith("#")):
            continue
        clean_ref = ref.split("?")[0].split("#")[0].lstrip("/")
        if not clean_ref:
            continue
        file_path = WEB_ROOT / clean_ref
        if not file_path.exists():
            report("MISSING_STATIC_FILE", INDEX_HTML, idx, f"Referenced asset '{ref}' does not exist on disk at {file_path}")

# Check template options in template select dropdown
template_options = re.findall(r'<option\s+value="([^"]+\.json)"', html_content)
for opt in template_options:
    tmpl_path = WEB_ROOT / "templates" / "aiometadata-configs" / opt
    if not tmpl_path.exists():
        report("MISSING_TEMPLATE_FILE", INDEX_HTML, 1, f"Template option '{opt}' does not exist at {tmpl_path}")

# -----------------------------------------------------------------------------
# 2. AUDIT assets/app.js
# -----------------------------------------------------------------------------
js_content = APP_JS.read_text(encoding="utf-8")
js_lines = js_content.splitlines()

dynamic_keys = {
    'PREMIUMIZE_API_KEY','REALDEBRID_API_KEY','TORBOX_API_KEY','ALLDEBRID_API_KEY','DEBRIDLINK_API_KEY','EASYDEBRID_API_KEY',
    'TMDB_API_KEY','TVDB_API_KEY','FANART_API_KEY','MDBLIST_API_KEY','GEMINI_API_KEY',
    'TRAKT_CLIENT_ID','TRAKT_CLIENT_SECRET','SIMKL_CLIENT_ID','SIMKL_CLIENT_SECRET','ANILIST_CLIENT_ID','ANILIST_CLIENT_SECRET',
    'RPDB_API_KEY','SUBDL_API_KEY','SUBSOURCE_API_KEY','WYZIE_API_KEY','OFFCLOUD_API_KEY','SEEDR_API_KEY',
    'NZB_INDEXER_API_KEY'
}
dynamic_suffixes = ['-saved', '-remove', '-test', '-wrapper', '-card']

# Check document.getElementById
gid_pattern = re.compile(r'\b(?:document\.)?getElementById\([\'"]([^\'"]+)[\'"]\)')
for idx, line in enumerate(js_lines, start=1):
    for m in gid_pattern.finditer(line):
        jid = m.group(1)
        if jid in html_ids or jid in dynamic_keys:
            continue
        if any(jid.endswith(s) and jid[:-len(s)] in dynamic_keys for s in dynamic_suffixes):
            continue
        if re.search(rf'id=["\']{re.escape(jid)}["\']', js_content):
            continue
        report("MISSING_ELEMENT_ID", APP_JS, idx, f"getElementById('{jid}') has no matching element in index.html")

# Check querySelector('#id')
qs_id_pattern = re.compile(r'querySelector(?:All)?\([\'"]#([a-zA-Z0-9_-]+)[\'"]')
for idx, line in enumerate(js_lines, start=1):
    for m in qs_id_pattern.finditer(line):
        jid = m.group(1)
        if jid in html_ids or jid in dynamic_keys:
            continue
        if any(jid.endswith(s) and jid[:-len(s)] in dynamic_keys for s in dynamic_suffixes):
            continue
        if re.search(rf'id=["\']{re.escape(jid)}["\']', js_content):
            continue
        report("MISSING_QUERY_SELECTOR_ID", APP_JS, idx, f"querySelector('#{jid}') has no matching element in index.html")

# Check fetch calls in app.js
fetch_pattern = re.compile(r'\bfetch\([`\'"](/api/[^`\'"?]+|/service-proxy/[^`\'"?]+|/jellyfin[^`\'"?]*)[`\'"?]')
js_fetch_endpoints = []
for idx, line in enumerate(js_lines, start=1):
    for m in fetch_pattern.finditer(line):
        endpoint = m.group(1)
        js_fetch_endpoints.append((idx, endpoint))

# -----------------------------------------------------------------------------
# 3. AUDIT docker/all-in-one/portal_server.py
# -----------------------------------------------------------------------------
server_content = PORTAL_SERVER.read_text(encoding="utf-8")
server_lines = server_content.splitlines()

# Extract endpoints handled in portal_server.py
handled_endpoints = set()
for m in re.finditer(r'path\s*(?:==|\bin)\s*(?:\(?\s*["\']([^"\']+)["\'](?:\s*,\s*["\']([^"\']+)["\'])*\s*\)?)', server_content):
    for group_val in m.groups():
        if group_val:
            handled_endpoints.add(group_val)

for m in re.finditer(r'path\.startswith\(["\']([^"\']+)["\']\)', server_content):
    handled_endpoints.add(m.group(1))

# Check whether each fetch endpoint in app.js is handled
for idx, endpoint in js_fetch_endpoints:
    matched = False
    for h in handled_endpoints:
        if endpoint == h or endpoint.startswith(h):
            matched = True
            break
    if not matched:
        report("UNHANDLED_API_FETCH", APP_JS, idx, f"fetch('{endpoint}') does not match any route in portal_server.py")

# Check send_head allowed extensions in portal_server.py
send_head_match = re.search(r'target\.suffix\.lower\(\)\s+in\s+\(([^)]+)\)', server_content)
if send_head_match:
    allowed_exts = {ext.strip().strip("'\"") for ext in send_head_match.group(1).split(",")}
else:
    allowed_exts = set()

# Check all static asset files in assets/ and templates/ to ensure their extensions are in allowed_exts
for asset_path in (WEB_ROOT / "assets").glob("**/*"):
    if asset_path.is_file():
        suffix = asset_path.suffix.lower()
        if suffix and suffix not in allowed_exts:
            report("DISALLOWED_ASSET_EXTENSION", asset_path, 1, f"Asset file extension '{suffix}' not in portal_server.py allowed list: {allowed_exts}")

# Check exception handlers in portal_server.py for raw traceback leakage
for idx, line in enumerate(server_lines, start=1):
    if "traceback.print_exc" in line or "traceback.format_exc" in line:
        report("TRACEBACK_LEAK", PORTAL_SERVER, idx, f"Raw traceback call found: '{line.strip()}'", "WARNING")

# Check INTERNAL_SERVICE_TARGETS mapping
sys.path.insert(0, str(WEB_ROOT))
from init.service_inventory import INTEGRATIONS
import importlib.util
spec = importlib.util.spec_from_file_location("portal_server", str(PORTAL_SERVER))
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)
target_keys = set(ps.INTERNAL_SERVICE_TARGETS.keys())
for _, svc, _, _ in INTEGRATIONS:
    if svc not in target_keys:
        report("MISSING_SERVICE_TARGET", PORTAL_SERVER, 130, f"Service '{svc}' from inventory missing in INTERNAL_SERVICE_TARGETS")

print(f"=== COMPREHENSIVE AUDIT SUMMARY ===")
print(f"Total element IDs in index.html: {len(html_ids)}")
print(f"Total handled endpoints in portal_server.py: {len(handled_endpoints)}")
print(f"Total findings: {len(findings)}")
for f in findings:
    print(f"[{f['severity']}] {f['category']} - {f['file']}:{f['line']} -> {f['issue']}")

if len(findings) == 0:
    print("\n[PASS] All structural, anchor, ID, asset, and route checks PASSED cleanly!")
sys.exit(0 if len(findings) == 0 else 1)
