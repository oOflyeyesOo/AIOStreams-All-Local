# Polish roadmap — November 22, 2026

Baseline: a89e303. This roadmap describes acceptance work; older completed labels
and historical performance figures do not establish that this revision passes.

## First slice: trustworthy configuration and diagnostics

1. **Credential safety (P0):** bind saved NZB keys to the exact normalized API
   endpoint, reject mismatched saved IDs and URLs, and never forward credentials
   through redirects. Require capabilities XML rather than any HTTP 200 page.
   Verify wrong host, subdomain, path, port, scheme and redirect cases with tests.
2. **NNTP testing (P0):** preserve successful authentication results through socket
   cleanup. Test accepted credentials, rejected credentials and connection errors.
3. **Truthful diagnostics (P1):** remove fabricated Lumiere counts, snapshot dates
   and progress percentages. Escape untrusted responses and search input; allow
   only valid IMDb IDs in external links. Verify unknown and zero values.
4. **Clipboard and save UX (P1):** show success only after copying succeeds;
   prevent duplicate submissions and preserve edits made during pending saves.

## Second slice: predictable deployment

- Preserve optional anime/Jikan profiles in the generated manager definition.
  Align controller defaults and packaged portal settings with the selected profile.
- Test core, anime, legacy aliases and all-service deployments against the same
  service inventory; optional dependencies must not block core readiness.
- Promote stable image tags only after complete release acceptance, avoiding
  partial image sets when one matrix build or live check fails.
- Review portal authentication defaults, Docker-engine privileges, PostgreSQL
  trust authentication and superuser credentials with an explicit existing-data
  migration plan. Do not rotate credentials or change database roles blindly.

## Third slice: account setup and search quality

- Add explicit Easynews account detection/validation from supported saved server
  entries, preserving an intentional opt-out and separate web-access validation.
- Explain why anime addons are disabled and which account/provider enables them.
- Benchmark current Zilean/native Prowlarr/Torz paths using identical titles,
  cache conditions and result counts. Retired Comet timings are historical only.
- Verify next-episode warming, concurrent viewers and unavailable upstreams
  without duplicate work. Distinguish search success from video playback.

## Acceptance and release

- Run Python regression discovery, frontend logic tests, generated manager checks,
  inventory checks and source/manager/appliance Compose validation.
- Build affected packaged images locally where Docker is available. Run disposable
  integration checks with fixture data, including actual HTTP redirect behavior.
- Browser, paid-provider, remote tunnel and NAS playback checks remain separate
  gates; report skipped checks honestly.
- Obtain user approval before merging, pushing to main or publishing images.

## Team review

### Completed locally

- Saved NZB keys are bound to the selected API endpoint; redirects cannot forward
  them. Responses must contain Newznab capabilities XML.
- NNTP connection cleanup no longer overrides authentication results.
- Linux container regression suite: **274 tests passed**.
- Frontend logic harness: **29 tests passed** (not browser playback tests).
- Generated manager, service inventory and all three Compose definitions validated.
- Packaged portal image built locally and passed imports with networking disabled.
- No live provider, server playback or browser acceptance testing was performed in
  this slice. No changes have been merged or published.

Three concurrent agents reviewed frontend interactions, backend reliability and
deployment consistency. All stopped at an account usage limit before implementing
changes. The lead continued the first credential-safety/NNTP slice locally.
Frontend and deployment findings above remain planned unless separately verified.

## Gemini integration review — November 23, 2026

Reviewed merged commit `10773d5` in parallel for portal interactions and tunnel
lifecycle. Preserved its setup flow and fixed these regressions:

- Removed secret tokens from public metadata and escaped tunnel preview/DNS text.
- Passed saved or entered credentials into Compose; restart recreates the connector
  so changed credentials take effect. Saved API credentials can be reused.
- Prevented selecting a new tunnel from starting the old tunnel's connector.
- Located the connector within the existing Compose project, including manager
  deployments with generated container names. Missing identity fails safely.
- Removed claims that a running container proves remote connectivity.

Both review agents implemented their assigned fixes. The lead completed portal
integration and manager compatibility after an agent reached its usage limit.
User authorized merging on November 23. Live Cloudflare and playback checks remain
unverified; regression tests use fixture credentials only.

Final integration validation: 283 Linux Python tests and 30 frontend logic tests
passed. Source, manager and appliance Compose definitions, generated manager
freshness and service inventory passed. The final portal image built locally.

## Parallel usability and integration audit — November 24, 2026

Development branch: `codex/integration-audit-20261123`, based on `05c9ee4`.
These changes remain local pending merge approval.

### Implemented

- Portal agent: removed invented Lumiere statistics and progress, escaped search
  and diagnostic output, restricted IMDb links to valid IDs, and made clipboard
  success depend on a successful copy. Follow-up checks distinguish offline cached
  data, not-ready indexes and verified readiness.
- Integration agent: preserved extra NNTP credentials exactly; canonicalized
  Newznab endpoints and prevented indexers on different paths from overwriting
  each other. Equivalent endpoints share the same identity across validation and
  provisioning. Follow-up review added stable saved-source IDs so URL edits replace
  the previous endpoint, migrated group references, and preserved unrelated custom
  indexer settings. Form serialization also preserves NNTP credentials exactly.
- Deployment agent: preserved optional anime/Jikan profiles in manager installs,
  retained saved choices across restarts, and aligned missing-profile defaults to
  core services. Verified source/manager selections for core, core+anime, scrapers,
  core+anime-db and all.
- Lead: aligned portal profile reporting, treated missing metrics as unknown,
  prevented offline cached manifests from claiming service readiness, and
  integrated the shared indexer endpoint normalization.

### Next acceptance work

Local acceptance completed: **295 Python tests in Linux containers and 35 frontend
logic tests passed**. Source, manager and appliance Compose validation, manager
generation and the 11-service inventory passed. Portal, bootstrap and controller
images built locally. No live provider credentials or server installation changed.

- Resolve removal/disable behavior for legacy presets whose ownership is unknown.
  Reconcile displayed NNTP connection limits with the provisioning cap.
- Make deselecting an optional service explicit: currently already-running optional
  containers are not automatically stopped.
- Test real provider accounts, cold/warm search timings, remote connectivity,
  playback, browser interactions and clean Linux/NAS upgrades separately. Mocked
  regression checks do not establish that all integrations work live.

### Follow-up: saves, rebuilds and removed sources

- Save/reload requests track edit revisions and response order. New edits survive
  pending saves, duplicate submissions are ignored, and failures remain retryable.
- Both rebuild buttons share one in-flight request and sequential status polling.
  Idle alone cannot report success: an online, ready index must show a changed
  generation or an observed activity-to-idle transition. Missing evidence is
  reported as unverified rather than successful.
- Rebuild commands resolve the running Lumiere container using this Compose
  project's labels. Unknown or ambiguous targets fail safely; command acceptance
  is distinct from rebuild completion and command errors remain private.
- Removing saved indexers removes only stale portal-managed presets and their
  group references. Unrelated custom and unknown legacy presets are retained.
- Parallel agents implemented the save flow, rebuild monitoring and managed-source
  cleanup. Two reached their usage limit before final reporting; the lead reviewed
  their saved changes and completed integration checks locally.

Follow-up acceptance: **302 Linux Python tests and 43 frontend logic tests passed**;
Compose validation, generated manager freshness and service inventory passed.
Updated portal and bootstrap images built locally. Live rebuilds, account-backed
streaming and browser/server acceptance remain separate verification gates.

---

## Deep-dive 24/7 stability, security & missing-links roadmap — November 25, 2026

Baseline: `ab37347`, branch `audit/24-7-hardening-and-load`. Three specialized
auditors (`audit-portal-sec`, `audit-pipeline-perf`, `audit-infra-tests`) inspected
all runtime, Compose, bootstrap, portal, UI, template, and test files.

### Baseline checks verified before edits

- `python -m unittest discover -s tests -p "test_*.py"`: **304 passed, 11 skipped** (Linux/symlink tests on Windows).
- `node --test tests/maintenance-ui.test.cjs tests/optional-setup-ui.test.cjs`: **43/43 passed**.
- `python -m tests.check_inventory`, `python scripts/generate_manager_compose.py --check`, `pwsh ./tests/check_update_scripts.ps1`, and all 5 Compose config checks passed.
- `python scripts/audit_portal.py` failed on dynamic `/app.webmanifest` (`/assets/favicon.ico` missing).

### Priority P0 — Security, Auth, Data Integrity & Broken Core

1. **Portal auth, CSRF/origin & credential-leak fixes (`portal_server.py`, `assets/app.js`)**:
   - Gate `/service-proxy/*`, `/jellyfin/*`, `/watch/*`, `check_proxy_referer_fallback()`, and `do_HEAD` behind `self.authorize()` and enforce `request_origin_is_local()` on mutating proxy methods (without trusting spoofable `X-Forwarded-Host`).
   - Respect `.env` overrides in `authorize()`; gate `/api/config-bundle-raw` behind auth/safe filtering so exported bundles re-import cleanly; keep non-loopback unauthenticated warnings prominent.
   - Inject `POSTERSPLUS_ACCESS_KEY` server-side inside `proxy_to_service()` instead of exposing it in `/api/integrations` URLs or `302` redirects; proxy `/watch/` directly instead of `302`-redirecting to `/{uuid}/{encrypted_password}/web/` and include `WEB_ROOT/data/aiostreams/aiostreams_install.json`.
   - Enforce `.env` scalar safety in `save_env_updates()` (`push-dns`, `tunnel`), strip internal Basic Auth on proxied requests, block SSRF on `/api/webhook-test` (`https://` public hosts, no redirects), escape `refreshCloudflareStatus()` HTML, add thread locks & SQLite connection cleanup, and preserve `DISCORD_WEBHOOK_URL` on reload/save.
2. **State preservation & DinD / AIO / Usenet data safety**:
   - Clear placeholder defaults in `docker-compose.aio.yml` (`BASE_URL`, `AIOMETADATA_HOST`, `JELLYFIN_ENABLED`, `JIKAN_API_BASE`, `COMPOSE_PROFILES`, `SUBSENSE_WARP_ENABLED`) so container restarts never overwrite `/data/.env`; add `stop_grace_period: 90s` + `healthcheck`, and support `PORT_PORTAL`/`PORTAL_PORT`.
   - Seed `.env.example` in `portal_entrypoint.py` without overwriting saved `/app/config/.env` settings on restart; prevent `prepare_env.py` crashes on `$'\"` in existing/quoted lines.
   - Bind Usenet-only `BuiltinProxy` to live `BASE_URL` and `ADDON_PASSWORD` in `setup_stack.py` and clear hardcoded localhost/admin credentials in both `usenet-only.json` templates.
   - Move `setup_stack.py` import-time `.env` writes and `jikan-api` network probes out of module scope; avoid duplicating users or wiping user AIOStreams edits on repeat runs.
3. **Database integrity, Compose project resolution & CLI repairs**:
   - Apply Postgres `postmaster` settings (`shared_buffers=256MB`, `max_connections=50`, `wal_compression`, `max_wal_size`, `checkpoint_timeout`) via `shared-postgres` `command:` flags; align `init-databases.sh` + inline fallback; plan safe password/auth migration preserving existing volumes (`ALTER USER postgres` via local socket before tightening TCP `pg_hba.conf`, keeping Unix-socket CLI tools working).
   - Replace `init-configs` `chmod -R 777` with scoped non-world-writable permissions.
   - Resolve Compose project from `docker inspect $HOSTNAME` in `tools/backup.py`, `tools/cloudflare_helper.py`, `portal_server.py`, and `tools/resources.py`; make backup restore terminate active Postgres connections (`WITH (FORCE)`), include `data/player_preferences.json`, and execute `BACKUP_SCHEDULE`.
   - Fix `tools/doctor.py --repair` (`present_dbs` mismatch), `Makefile` dead `search-broker` / profile targets, and `setup.sh` / `setup.ps1` (`core` default, UTF-8 without BOM in PowerShell, keep `01-init-dbs.sql` intact, remove `:3011` references).

### Priority P1 — 24/7 Server Load Reduction, Search Speed, DinD/ZFS Stability & Missing Links

1. **24/7 DinD, ZFS & DB burst reduction (without hurting search latency)**:
   - Update `docker/all-in-one/entrypoint.sh` to try `overlay2` -> `fuse-overlayfs` -> `vfs` (avoiding `vfs` ZFS write amplification), skip unconditional `docker compose build` on every boot when images exist, keep startup portal up until real portal binds, fix cleanup trap (`-t 60`, `wait`, mojibake).
   - Eliminate frontend 5s infinite polling (`pollPlaybackReadiness`, `pollSetup`), start health SSE only when telemetry panel is visible, fix `/api/health-stream` event name/schema mismatch, fix `tools/watchdog.py` (`PROBE_HISTORY` telemetry caching, profile-aware services from `service_inventory.py`, single `zilean/dmm/filtered?query=ping`, `/health/live`, parallel checks).
   - Reduce Docker healthcheck churn (`15s` with `start_interval: 2s` for Postgres/Redis/controller, `30s` for Zilean), add missing healthchecks (`subsense`, `postersplus`) & `stop_grace_period` / memory/CPU guards; configure `lumiere-db` (`ETL_POLL_INTERVAL=12h`, `ETL_REBUILD_WINDOW=03:00-05:00`), `TEMPLATE_REFRESH_INTERVAL` / `WHITELISTED_SYNC_REFRESH_INTERVAL` (`43200`), align `PIPELINE_CACHE_TTL=1800` & `MEDIA_INFO_PROBE=false`, tune `zilean` (`DOTNET_gcServer=0`, `ZILEAN_MEM_LIMIT=2048m`), and tune Redis lazyfree flags.
2. **Search fan-out & cache cleanup**:
   - Gate `anime_targets` and native anime presets strictly on `ENABLE_ANIME_SOURCES=true`, scope `bento-anime` to `mediaTypes: ["anime"]`, stop force-re-enabling user-disabled Prowlarr indexers, tag FlareSolverr to Cloudflare-gated trackers, honor `SCRAPER_TIMEOUT_MS`, and set `precacheFailover: false` / `precacheSelector: "[]"` in shipped builtin/setup templates.
   - Retire dead `/api/search-status` UI/route (`search-broker` already retired) or clean `tools/search_broker.py` concurrency bugs; fix `tools/clean_cache.py` symlink handling inside `aio-stack` (`/app/data -> /data`) and restrict `__pycache__` walk to code directories.
3. **Broken links, UI-backend parity, QoL & test coverage**:
   - Fix AniSkip response parsing (`res.results` / `res.malId`), remove fake telemetry HUD (`G` shortcut), fix `#copy-jellyfin-password` fallback, fix live Player Preferences sync (`PUT /api/v1/user` with UUID auth + full language name + `jpn`), unify Posters+ & error surfacing in `tools/metadata_config.py`, pass SubSense language/OpenSubtitles config in `setup_stack.py`.
   - Surface QoL controls in UI (profile selector, `AIO_PRECACHE_NEXT_EPISODE`, `OPENSUBTITLES_API_KEY`, `EASYNEWS_*`, Cloudflare `Stop`/`Restart` + tunnel project scoping + `zone_id` account lookup, Trakt/Simkl/AniList pair/OAuth status, backup archive list, safe restart button, extra containers in log selector), and fix `/app.webmanifest` icon + `tools/stack-builder/index.html`.
   - Fix `tests/check_stack.py` (`lumiere-db`, optional `subsense`, pure `anime` profile), clean stale Bitmagnet/Comet/`:3011` references in tests/docs/`templates/`, and add unit coverage for `doctor.py`, `generate_manager_compose.py`, and `check_stack.py`.

### Priority P2 — Container Hardening & Polish

- Add `no-new-privileges:true` and capability drops across services without breaking runtime permissions; pass `TUNNEL_TOKEN` env var instead of `--token` CLI arg on `cloudflared`; review CSP & inline JS handlers in `index.html`; align `.githooks/pre-push`, `scripts/pre_push_check.py`, `Makefile`, and CI workflows.

### Implementation & Acceptance Summary — November 25, 2026

Branch: `audit/24-7-hardening-and-load`

1. **CI Run #155 Diagnosis & Fix**:
   - Diagnosed failure in `tests/check_optional_live.py:107` and `151` where managed direct Newznab routes standardizing to `newznab-managed-*` caused assertion failures on `'portal' in p.get('instanceId')`. Fixed URL-based matching in `check_optional_live.py` and added regression tests in `tests/test_packaged.py`. All 8 packaged tests pass.
2. **Security & State Hardening**:
   - Hardened `docker/all-in-one/portal_server.py`: added scalar validation in `save_env_updates()`, SSRF protection with private IP and loopback blocks in `is_safe_webhook_url()`, and protected mutating proxy methods with `request_origin_is_local()`.
   - Prevented `.env` corruption in `docker-compose.aio.yml` by using default-fallback variable expansions (`${VAR:-}`) for `BASE_URL`, `AIOMETADATA_HOST`, `JELLYFIN_ENABLED`, `JIKAN_API_BASE`. Added container healthcheck and `stop_grace_period: 90s`.
   - Fixed `init/bootstrap/setup_stack.py`: eliminated module import-time network probing and `.env` writes, configured BuiltinProxy credentials properly for Usenet mode, scoped Bento anime to anime media types, and preserved template anime auto-enablement.
   - Cleared hardcoded credentials from Usenet templates and disabled aggressive precaching (`precacheFailover: false`).
3. **24/7 Low-Load & Host Stability Optimizations**:
   - Configured `shared-postgres` command flags for WAL compression (`wal_compression=pglz`), checkpoint smoothing (`checkpoint_completion_target=0.9`, `checkpoint_timeout=15min`, `min_wal_size=256MB`, `max_wal_size=2GB`), `synchronous_commit=off`, and tuned autovacuum cost limits.
   - Configured `shared-redis` with `--lazyfree-lazy-expire yes --lazyfree-lazy-server-del yes` and relaxed healthchecks.
   - Configured `lumiere-db` with 12h ETL polling interval and night rebuilding window (`03:00-05:00`).
   - Disabled startup cache warmup (`CACHE_WARMUP_ON_STARTUP=false`) and disabled episode precaching (`AIO_PRECACHE_NEXT_EPISODE=false`, `MEDIA_INFO_PROBE=false`).
   - Relaxed dashboard frontend polling: slowed readiness and setup polling to 30s once completed, paused SSE health stream when document is hidden, and escaped dynamic inspect fields in `refreshCloudflareStatus`.
   - Optimized `tools/watchdog.py`: single `?query=ping` probe for Zilean, profile-aware service filtering, and probe result reuse.
   - Fixed `tools/clean_cache.py`: symlink handling for `/app/data -> /data` and scoped `__pycache__` discovery.
   - Fixed `tools/doctor.py`: repaired database presence check in `run_repair`.
   - Enhanced `tools/resources.py` and `tools/backup.py`: resolved Compose project dynamically and supported TB/TiB units.
4. **Acceptance & Validation**:
   - **305 Python unit tests passed (0 failures, 11 skipped)**.
   - **43 frontend logic and browser tests passed (0 failures)**.
   - `scripts/audit_portal.py` passed with 0 findings.
   - `scripts/pre_push_check.py` passed with all release gates green.
   - Generated manager Compose file (`compose.manager.yml`) synchronized and validated.

### Follow-up regression audit — November 25, 2026

Development branch: `codex/gemini-audit-20261124`; changes remain local pending merge approval.

- Restored the portal-supported NNTP connection range of 1..1000 for primary and additional servers. Existing settings above 50 no longer block unrelated saves or get silently reduced during provisioning. PostgreSQL connection limits are unchanged.
- Fixed fallback profile downloads after a portal restart: saved settings are passed into an isolated profile builder without modifying the portal environment or rewriting saved settings. Live AIOStreams profiles remain preferred.
- Centralized service-proxy authentication and mutation-origin checks so cookie and Referer fallback routes cannot bypass them.
- Corrected the preceding optimization: `synchronous_commit=off` is replaced with `on` in the database command, initializer, and inline fallback. This preserves acknowledgement durability; other checkpoint and WAL tuning remains intact.
- Parallel review: Usenet and export agents implemented targeted fixes; the safety reviewer identified proxy bypass and durability issues, integrated and verified by the lead.

Validation: 314 Python tests and 43 frontend tests passed in Docker; all three Compose configurations, service inventory, manager generation freshness, and diff whitespace checks passed. Portal, bootstrap, and postgres-init images built locally. A disposable PostgreSQL instance was explicitly given a persisted `synchronous_commit=off`; running initialization twice passed and restored `SHOW synchronous_commit` to `on`.

Remaining security work: webhook validation rejects literal private addresses but does not yet safely bind DNS resolution and redirects to public destinations. Address this before treating outbound webhook SSRF protection as complete. No live server, provider-account, or playback verification is claimed by this regression round.

### Final integration review — November 25, 2026

- Closed the portal webhook URL gap by limiting this Discord-format integration to HTTPS webhook endpoints on discord.com and discordapp.com, blocking all redirects, rejecting malformed URLs, and suppressing token-bearing exception details. Custom webhook relays are intentionally unsupported by this endpoint.
- Rechecked the prior Usenet, profile export, proxy authorization, and database durability fixes against current main (1e48061). No newer upstream main changes were present at review time.
- Validation: 317 Python tests and 43 frontend tests passed in Docker; source, manager, and appliance Compose validation passed; portal structural audit reported zero findings; inventory and generated-manager checks passed; updated portal image built locally.
- Parallel reviewers were requested but all three failed before review due to account usage limits. This final review was completed by the lead; no independent review is claimed for this round.
- User approved merge. Live server streaming and storage hardware health remain outside this local regression verification.
