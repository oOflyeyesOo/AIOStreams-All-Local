# AIO Local roadmap

Updated 2026-11-07. The product goal remains: deploy through Docker Compose or a management app, enter keys on one page, and receive manifests for compatible players. Prioritize a dependable installation over adding more services.

Copilot's original suggestions are retained in [docs/COPILOT-ROADMAP.md](docs/COPILOT-ROADMAP.md). Completed work and limits are recorded in [feature validation](docs/FEATURE-VALIDATION.md), [streaming/package validation](docs/TRACING-AND-PACKAGING.md), and [release validation](docs/RELEASE-VALIDATION.md).

## Verified baseline

- [x] Source and prebuilt manager deployments; all eight packaged images published.
- [x] Fresh image-only stack, 21 internal endpoint checks, and portal/controller apply.
- [x] Movie and episode HTTP range reads and 15-second media decode.
- [x] Request tracing: default slow-source timeout removed; sampled repeated internal requests reuse cache without identical repeated upstream targets.
- [x] Live fixture PostgreSQL backup/delete/restore, SQLite snapshots, Prowlarr backup coverage, fresh backup downloads and safe cache cleanup.
- [x] Update failure handling in Bash and PowerShell; 89 regression tests and latest CI workflows passing.
- [x] Corrected OAuth client wiring and preservation of saved account links on repeated setup.
- [x] Supplied keys removed from development copies, current release files and reachable Git history/tags. Original installation and original backup remain unchanged by explicit request.

These checks do not establish every external integration as working. Real OAuth consent/token refresh, an authenticated tunnel, other debrid providers, NNTP and ARM/NAS compatibility remain unverified. Endpoint health is separate from functional playback.

## Next milestones

### 1. Reproducible releases and recoverable upgrades — next

**Outcome:** an operator can install a known version, upgrade it and recover without losing profiles or keys.

- [ ] Publish a tested release manifest that pins packaged components and upstream images to a known set of versions/digests; avoid mixing independently changing `latest` images.
- [ ] Add an update preview showing versions, downloads, migrations and required restarts.
- [ ] Create and verify a backup before an upgrade; stop on backup, download, migration or readiness failure.
- [ ] Test an upgrade and rollback between two actual release sets using named volumes and fixture accounts/data.
- [ ] Document recovery for custom PostgreSQL roles, older archive formats and database migrations that cannot be reversed by changing an image tag.
- [ ] Prevent documentation-only edits from rebuilding/publishing every image.

**Exit gate:** fresh install -> fixture data -> upgrade -> failed-upgrade recovery/rollback preserves stored data, provider configuration, profile identity and installed manifest URLs. Published image references resolve to the tested versions.

### 2. Honest, simpler setup and maintenance

**Outcome:** the single page explains what is ready and offers the next useful action.

- [ ] Distinguish missing credentials, configured integration, successful authorization, service readiness and verified playback.
- [ ] Surface resource use, backup status and safe cleanup controls on the existing page; keep optional integrations under advanced settings.
- [ ] Show when the last backup succeeded and whether PostgreSQL was included; never present a partial backup as complete.
- [ ] Guide users from tracking app credentials to the upstream account-connection screen, then show connected/disconnected status.
- [ ] Audit first-run credentials and password rotation; remove default-password assumptions from installation instructions.
- [ ] Audit Docker-engine access: the portal currently needs it for maintenance as well as the controller for setup. Correct documentation and evaluate moving maintenance behind narrow controller actions.
- [ ] Refresh desktop/mobile screenshots using an empty or fixture configuration, with no live keys or personalized URLs.

**Exit gate:** a new operator completes setup in one page, can identify a failed dependency and recover, and can download a current, clearly labeled backup. Browser tests cover errors, disabled actions and mobile layouts.

### 3. Complete optional integrations end to end

**Outcome:** each integration has a verified account lifecycle or an explicit unverified label.

- [ ] Trakt, Simkl and AniList: real consent, token refresh, expiry, reconnect and revocation; repeat setup must preserve links.
- [ ] Verify watchlist import, watched history and scrobbling separately for the services that support each operation; check account isolation.
- [ ] Test remote access with an authenticated tunnel or reverse proxy: public manifest URLs, metadata/artwork, subtitles, CORS, range requests and reconnects.
- [ ] Validate subtitle language selection and fallback with available providers.
- [ ] Test additional debrid providers and Usenet only when their accounts and infrastructure are available; retain safe missing-credential behavior.
- [ ] Record which tracking service owns watched-state updates to avoid conflicting sync loops or duplicate scrobbles.

**Exit gate:** a dated support matrix distinguishes live-tested, fixture-tested, unavailable and unsupported behavior. No application client ID or raw access token is treated as an OAuth-record ID. Optional failures do not block the core streaming path.

**Dependencies:** test accounts/app credentials and a tunnel/domain where appropriate. Do not reuse or copy the user's retained installation keys into source or development environments.

### 4. Cold-search performance and cancellation

**Outcome:** cold searches are bounded and repeated searches do not multiply background work.

- [ ] Extend privacy-preserving traces to additional request edges; distinguish different search forms from exact duplicates.
- [ ] Investigate Prowlarr TV searches that continue after the player has already received a response.
- [ ] Add cancellation, bounded concurrency and in-flight request coalescing where supported.
- [ ] Evaluate cache-first discovery and selective fallback; keep slow direct scrapers opt-in unless measurements justify changing the default.
- [ ] Measure cold/warm movie, episode and anime lookups, unavailable indexers, concurrent viewers and memory pressure on a documented reference host.
- [ ] Set latency/resource budgets from those measurements and guard against regressions with deterministic fixtures.

**Exit gate:** a repeatable report shows cold/warm timings, request counts, cancelled work and peak memory. No claim of duplicate-free external traffic is made beyond the instrumented coverage.

### 5. Platform and player acceptance

**Outcome:** installation guidance matches hardware and players actually tested.

- [ ] Repeat clean install, restart and upgrade on a Linux server and at least one NAS/management-app environment.
- [ ] Verify Portainer/Dockge deployment from an empty host with private-registry credentials where required.
- [ ] Audit ARM64 availability for every upstream image before adding ARM builds; document blockers and supported substitutions.
- [ ] Test Stremio desktop/mobile/web and Nuvio for install links, persistent guest/signed-in profiles, subtitles and actual media decoding.
- [ ] Test anime ID normalization after consolidating mapping ownership in AIOStreams.
- [ ] Document which clients consume the manifest directly and which require an external player or streaming server.

**Exit gate:** a hardware/player matrix lists tested versions and limitations. Do not advertise ARM, every NAS or every player until the corresponding path passes.

## Working rules

1. Complete one milestone's acceptance checks before broadening its claims.
2. Use disposable projects and fixture data for destructive tests; preserve the existing installation and original backup.
3. Keep live credentials, OAuth tokens, signed media URLs and runtime data out of Git, images, logs and screenshots.
4. Attach regression coverage to concrete bugs and repeat live checks when the affected deployment path changes.
5. Keep one generated manager definition aligned with source Compose; validate both in CI.

**Recommended next work:** milestone 1, starting with a version-pinned release manifest and a disposable upgrade/rollback test. Continue OAuth/tunnel testing when dedicated test accounts are available.
