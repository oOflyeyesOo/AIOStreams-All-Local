# AIO Local Completion Roadmap

This roadmap is the recommended path from the current `v1.2.0` snapshot to a
reliable, documented, production-ready self-hosted appliance. It prioritizes
reproducibility and a working core over adding more services.

## North-star release

An operator should be able to:

1. Install on Linux, Windows, or a supported NAS with one documented command.
2. Configure one supported debrid account and TMDB in the portal.
3. Receive a valid AIOStreams manifest and optional AIOMetadata manifest.
4. Install both manifests in Stremio or use the bundled web player.
5. Search, select, subtitle, and play a movie and an episode remotely.
6. Upgrade, back up, restore, diagnose, and roll back without losing profiles
   or credentials.

“Complete” means every advertised integration is either verified in CI or
clearly marked optional and manually tested. A reachable TCP port alone is not
an integration test.

## Current baseline

The repository already contains:

- A Compose appliance with core, scraper, proxy, web, tunnel, and all-in-one
  profiles in [`docker-compose.yml`](./docker-compose.yml).
- A setup portal and bootstrap/configuration path in
  [`docker/all-in-one/portal_server.py`](./docker/all-in-one/portal_server.py)
  and [`init/bootstrap/setup_stack.py`](./init/bootstrap/setup_stack.py).
- Local templates for AIOStreams filtering, expressions, formatters, regex
  rankings, metadata, and setup presets in [`templates/`](./templates/).
- Unit, failure-mode, browser bootstrap, database initialization, and live
  probes in [`tests/`](./tests/).
- Backup, cache cleanup, resource monitoring, and a client-side stack builder
  in [`tools/`](./tools/).

The release is not yet a trustworthy completion point because:

- The stale packaged-manager workflow and its missing generated-manifest
  references have been removed, but CI still needs to guard the remaining
  workflow inputs and supported Compose profiles.
- The Compose deployment, all-in-one deployment, and workflow deployment are
  three different release surfaces without one shared generated manifest.
- Documentation now identifies 19 application services separately from portal,
  databases, initialization jobs, and optional tunnel infrastructure; future
  service additions must update the shared inventory and count together.
- Most upstream images use `latest`, so a rebuild is not reproducible.
- The live E2E suite contains fallback/test credentials and depends on real
  external services, making it unsuitable as the only release gate.
- Usenet, remote playback, reverse-proxy/TLS, provider entitlement, restore,
  and multi-platform behavior need a repeatable acceptance matrix.

## Recommended execution order

### Phase 0 — Make the repository releasable

**Goal:** every clean checkout can validate and build the intended artifacts.

- Decide whether packaged manager images are still supported. If yes, restore
  the missing generator, packaged Dockerfile, and generated
  `compose.manager.yml`. If no, remove the stale workflow and references.
- Add a CI preflight that checks every workflow-referenced file exists.
- Run Compose validation for the default stack, every supported profile, the
  all-in-one file, and the test file.
- Make the service inventory data-driven so the portal, README, health page,
  Compose comments, and tests use the same names, ports, groups, and optional
  status.
- Add a `make`/script entry point (or equivalent) for `validate`, `test`,
  `e2e`, `build`, `backup`, and `restore`; keep the Docker commands underneath
  it for portability.

**Exit gate:** a clean checkout passes CI without missing-file errors, and the
README service/profile counts are generated or verified from one source.

### Phase 1 — Freeze the supported core path

**Goal:** prove the smallest useful installation before expanding coverage.

Support and test this path first:

`portal -> AIOStreams -> Comet -> one debrid provider -> TMDB -> SubSense ->`
`Stremio manifest -> movie playback + episode playback`.

- Choose the primary provider for the documented smoke path (recommended:
  Real-Debrid or TorBox) and make the other providers optional adapters.
- Pin image digests or tested version tags for every production image; add a
  documented update process for changing pins.
- Define health semantics: process health, dependency readiness, manifest
  readiness, provider authentication, and playback are separate states.
- Ensure setup is idempotent: a second run must not duplicate indexers,
  overwrite existing secrets, or invalidate installed manifests.
- Add deterministic fixtures/mocks for portal, bootstrap, provider validation,
  manifest generation, and failure handling.
- The portal now exposes separate process, dependency, manifest, and version
  health endpoints; Prowlarr repeat setup has deterministic idempotency
  coverage, and backup/restore has fixture and archive-safety coverage.
- Add live smoke tests that never print or commit credentials and skip cleanly
  when optional provider secrets are absent.

**Exit gate:** a fresh install and a repeat setup both produce working movie and
episode manifests, with a documented diagnosis for each failed dependency.

### Phase 2 — Secure deployment and data lifecycle

**Goal:** make the default safe for an internet-exposed host.

- Keep only the intended ingress ports public; verify loopback binding in an
  automated test rather than relying on documentation.
- Require a non-default portal password on first setup and add password rotation.
- Audit all generated URLs and logs for API keys, signed stream URLs, cookies,
  and database passwords.
- Remove credentials and realistic-looking tokens from live tests; use injected
  secrets or fixtures.
- Add CSRF/origin protection for state-changing portal endpoints, rate limits
  for authentication and setup, and bounded request timeouts.
- Document reverse proxy/TLS configurations for Caddy, Traefik, Nginx, and
  Cloudflare Tunnel. Include WebSocket, range-request, large-header, and
  streaming timeout requirements.
- Test `backup.py` and restore with a disposable installation. Define what is
  backed up (`.env`, persistent data, generated config) and what is rebuilt.
- Add a rollback procedure for image pin changes and failed migrations.

**Exit gate:** a security review finds no default-password, secret-leak, public
internal-port, or unrecoverable-upgrade blocker; backup/restore passes on a
clean host.

### Phase 3 — Complete and verify integrations

Treat each row as an adapter with configuration, health behavior, test fixture,
documentation link, and an explicit “optional if unavailable” policy.

#### Streaming and debrid providers

| Integration | Configuration | Primary link | Verification |
|---|---|---|---|
| Real-Debrid | `REALDEBRID_API_KEY` | <https://real-debrid.com/apitoken> | auth, cached lookup, range playback |
| TorBox | `TORBOX_API_KEY` | <https://torbox.app/settings> | auth, search, playback |
| AllDebrid | `ALLDEBRID_API_KEY` | <https://alldebrid.com/apikeys> | auth, resolve, playback |
| Premiumize | `PREMIUMIZE_API_KEY` | <https://www.premiumize.me/account> | auth, transfer/cache, playback |
| Debrid-Link | `DEBRIDLINK_API_KEY` | <https://debrid-link.com/webapp/register> | auth, resolve, playback |
| EasyDebrid | `EASYDEBRID_API_KEY` | <https://www.easydebrid.com/> | auth and resolve, if enabled upstream |
| Offcloud | `OFFCLOUD_API_KEY` | <https://offcloud.com/> | auth and resolve |
| Seedr | `SEEDR_API_KEY` | <https://www.seedr.cc/> | auth and resolve |
| Debrid Search | no separate key | service in Compose | personal-library query per supported provider |

#### Metadata, artwork, catalogs, and tracking

| Integration | Configuration | Primary link | Verification |
|---|---|---|---|
| TMDB | `TMDB_API_KEY` | <https://www.themoviedb.org/settings/api> | movie/series IDs and posters |
| TVDB | `TVDB_API_KEY` | <https://thetvdb.com/dashboard/account/apikeys> | episode/season metadata |
| Fanart.tv | `FANART_API_KEY` | <https://fanart.tv/get-an-api-key/> | logos/backgrounds |
| MDBList | `MDBLIST_API_KEY` | <https://mdblist.com/preferences/> | catalog import |
| RPDB | `RPDB_API_KEY` | <https://ratingposterdb.com/> | rating badge overlay |
| AIOMetadata | `AIOMETADATA_HOST` | project image/config in Compose | manifest, catalogs, artwork |
| Anime Kitsu | bundled service | <https://kitsu.io/> | anime catalog when the self-hosted service is running |
| Trakt | `TRAKT_CLIENT_ID`, `TRAKT_CLIENT_SECRET` | <https://trakt.tv/oauth/applications> | login, watchlist, scrobble |
| Simkl | `SIMKL_CLIENT_ID` | <https://simkl.com/settings/developer/> | list sync |
| AniList | `ANILIST_TOKEN` | <https://anilist.co/settings/developer> | anime list sync |
| Gemini | `GEMINI_API_KEY` | <https://aistudio.google.com/> | recap/translation opt-in |

#### Subtitles, discovery, proxies, and players

| Area | Integrations in this repository | Completion work |
|---|---|---|
| Subtitles | SubSense, OpenSubtitles, SubDL, SubSource, Wyzie/YIFY paths | test language selection, fallback ordering, and missing-key behavior |
| Discovery | Prowlarr, FlareSolverr, Zilean, Comet, Search Broker, Torrentio, RemuxDB | fixture indexers; live test only one controlled indexer |
| Proxies | BuiltinProxy, StremThru | test signed URLs, redirects, HTTP 206, and multi-IP shield boundaries |
| Usenet | InfiniDysk, NNTP credentials, NZB/indexer path | complete provider setup and playback or label as experimental |
| Players | Stremio, Stremio Web, Nuvio Web | test install links, profiles, CORS, range requests, and mobile layouts |
| Sync | SlickSync, Trakt, Simkl, AniList | test auth lifecycle, token storage, revoke, and conflict behavior |
| Remote access | Cloudflare Tunnel plus reverse proxies | publish only AIOStreams/AIOMetadata and verify DNS/TLS instructions |

**Exit gate:** every advertised integration has a green automated test, a
manual-test recipe, or an explicit experimental label in the portal and docs.

### Phase 4 — Operability and performance

**Goal:** users can understand and maintain a running stack.

- Add a machine-readable `/health`, `/ready`, `/version`, and build-info view.
- Show dependency-specific setup failures in the portal, not only a generic
  “failed” state.
- Add structured logs with correlation/request IDs and redaction tests.
- Add resource thresholds and cache controls based on
  [`tools/resources.py`](./tools/resources.py) and
  [`tools/clean_cache.py`](./tools/clean_cache.py).
- Benchmark the core, scraper, proxy, and all profiles on low-memory hosts.
- Define latency/error budgets for manifest, catalog, stream selection, and
  first-byte playback.
- Add update checks that report available versions without silently updating.
- Test restart ordering, Redis/Postgres recovery, disk-full behavior, and
  external service timeouts.

**Exit gate:** a user can identify a failed dependency from the portal/logs and
recover without deleting the whole data directory.

### Phase 5 — UX, distribution, and community release

**Goal:** make installation and contribution predictable.

- Unify `setup.sh`, `setup.ps1`, portal setup, Compose, and all-in-one defaults.
- Support explicit architecture policy (amd64 first; arm64 only when every image
  and player path is verified).
- Add import/export of a redacted configuration, provider key rotation, and
  profile presets.
- Add accessibility checks, keyboard navigation, localization-ready strings,
  and mobile validation for the setup portal.
- Publish a compatibility table for Docker/Compose versions, OS/NAS targets,
  browsers, and supported players.
- Add a release checklist, changelog, upgrade notes, and signed/versioned
  container tags.
- Add contribution guidance for adding a service, provider, template, or test.

**Exit gate:** a first-time user can install from the README without tribal
knowledge, and a contributor can add an integration without editing unrelated
surfaces.

## Release gates

Do not call a release complete until all gates below are green:

1. **Static:** YAML, shell, Python, JavaScript, and generated-file validation.
2. **Unit:** all tests under [`tests/`](./tests/).
3. **Compose:** default, `core`, `scrapers`, `proxies`, `web`, `tunnel`, and
   all-in-one configuration validation.
4. **Install:** fresh setup on a disposable host.
5. **Repeatability:** second setup, restart, upgrade, and rollback.
6. **Core E2E:** manifest, catalog, stream selection, subtitles, and HTTP range
   playback for one movie and one episode.
7. **Security:** no secret leakage, safe public bindings, auth/rate limits, and
   SSRF/redirect checks.
8. **Recovery:** backup, restore, database reinitialization, and partial-service
   failure.
9. **Docs:** every required value, public URL, port, profile, and known
   limitation agrees with the implementation.

## Suggested milestone sequence

| Milestone | Scope | Result |
|---|---|---|
| M0 | Phase 0 | CI and deployment surfaces are internally consistent |
| M1 | Phases 1–2 | Secure, repeatable core streaming appliance |
| M2 | Phase 3 streaming/catalog integrations | Provider and metadata matrix is trustworthy |
| M3 | Phase 3 subtitles/proxies/players/Usenet | Full advertised feature set or clear experimental labels |
| M4 | Phase 4 | Observable, recoverable, resource-bounded operation |
| M5 | Phase 5 | Versioned public release with install and contributor docs |

The critical path is **M0 → M1 → M2 → M4 → M5**. M3 can proceed in parallel
after M1, but it must not delay hardening the core path or be used to mask
missing release validation.
