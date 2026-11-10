# AIO Local roadmap

Updated 2026-11-08. The product goal remains: deploy through Docker Compose or a management app, enter keys on one page, and receive manifests for compatible players. Prioritize a dependable installation over adding more services.

Copilot's original suggestions are retained in [docs/COPILOT-ROADMAP.md](docs/COPILOT-ROADMAP.md). Completed work and limits are recorded in [feature validation](docs/FEATURE-VALIDATION.md), [streaming/package validation](docs/TRACING-AND-PACKAGING.md), and [release validation](docs/RELEASE-VALIDATION.md).

## Verified baseline

- [x] Source and prebuilt manager deployments; all nine packaged images published, plus the appliance image.
- [x] Fresh image-only stack, 22 internal endpoint checks, and portal/controller apply; exact digest-pinned bundle also passed on a fresh Linux runner.
- [x] Movie and episode HTTP range reads and 15-second media decode.
- [x] Request tracing: default slow-source timeout removed; sampled repeated internal requests reuse cache without identical repeated upstream targets.
- [x] Live fixture PostgreSQL backup/delete/restore, SQLite snapshots, Prowlarr backup coverage, fresh backup downloads and safe cache cleanup.
- [x] Update failure handling in Bash and PowerShell; 123 Python tests, 12 browser checks and source release CI passing.
- [x] Corrected OAuth client wiring and preservation of saved account links on repeated setup.
- [x] Reproduced and fixed first-start password migration failure; explicit configuration access keys, rejected unauthorized writes and a zero-restart release gate.
- [x] Supplied keys removed from development copies, current release files and reachable Git history/tags. Original installation and original backup remain unchanged by explicit request.

These checks do not establish every external integration as working. Real OAuth consent/token refresh, an authenticated tunnel, other debrid providers, paid NNTP decoding and ARM/NAS compatibility remain unverified. Endpoint health is separate from functional playback.

## Next milestones

### 1. Reproducible releases and recoverable upgrades — implementation and acceptance

**Outcome:** an operator can install a known version, upgrade it and recover without losing profiles or keys.

- [x] Generate digest-pinned packaged/upstream release bundles; gate upload on startup, endpoint and actual-AIOStreams routing tests.
- [x] Preview changed/removed images and require migration review; download sizes and automatic migration detection remain unavailable.
- [x] Verify fresh SQL/configuration/profile backups before replacing services; stop on download, startup or controller failure.
- [x] Exercise two immutable local fixture image sets: upgrade, snapshot rollback and injected failed-upgrade recovery preserve identity/data. Published-version migration compatibility remains a separate gate.
- [x] Document custom-role, legacy archive and database migration limits in [release recovery](docs/IMMUTABLE-RELEASES.md).
- [x] Exclude documentation-only changes from image build triggers.

**Exit gate:** fresh install -> fixture data -> upgrade -> failed-upgrade recovery/rollback preserves stored data, provider configuration, profile identity and installed manifest URLs. Published image references resolve to the tested versions.

### 2. Honest, simpler setup and maintenance

**Outcome:** the single page explains what is ready and offers the next useful action.

- [x] Display missing/configured keys separately from reachable services; authorization/playback explicitly unverified until tested.
- [x] Surface resource use, backup status, search activity and confirmed safe cleanup on the existing page.
- [x] Show backup time, SQL coverage and partial/unverified state; upgrade requires saved-profile coverage too.
- [ ] Guide users from tracking app credentials to the upstream account-connection screen, then show connected/disconnected status.
- [ ] Audit first-run credentials and password rotation; remove default-password assumptions from installation instructions.
- [x] Correct Docker-engine access documentation: both portal and controller mount the socket. Moving maintenance behind narrower actions remains outstanding.
- [x] Verify desktop/mobile maintenance layout and save fixture-only screenshots; eight browser regression checks pass.

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

- [x] Add resource/caller-aware native-path trace listeners and bounded event storage; only instrumented edges establish call counts.
- [ ] Investigate Prowlarr TV searches that continue after the player has already received a response.
- [x] Add bounded search admission, identical-request sharing, cache and failure cooldown; cancelling Prowlarr's server-side work remains outstanding.
- [x] Validate sequential Sootio fallback in actual AIOStreams: cached primary skips it; empty/failed primary invokes it once. Explicit off/parallel modes remain available.
- [ ] Measure cold/warm movie, episode and anime lookups, unavailable indexers, concurrent viewers and memory pressure on a documented reference host.
- [x] Record deterministic movie/episode/error/concurrent routing budgets and broker bounds in [routing validation](docs/ROUTING-VALIDATION.md). Full-host pressure budgets remain outstanding.

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

**Current acceptance:** [immutable release and recovery](docs/IMMUTABLE-RELEASES.md), [timed routing and limits](docs/ROUTING-VALIDATION.md). Finish the unchecked operator/authentication and cold-load gates before claiming milestones 1/2/4 universally complete. Continue OAuth/tunnel testing with dedicated accounts.

## Current source and optional-integration acceptance

- [x] Native Torrentio, RemuxDB, and DMM integration: four titles added 92/76/60/68 provider-cached hashes beyond Comet; selectable options querying public/curated databases.
- [x] Native addon parsing and new feature settings validated in an isolated AIOStreams profile; TMDB-dependent registration bug fixed.
- [x] Background prefetch opt-in; one native Torrentio route and bounded Sootio fallback.
- [x] Optional MediaFusion container/preset switch; configured-manifest input for external integrations.
- [x] Usenet form configures actual InfiniDysk headless provider settings and a Usenet-only Prowlarr preset.
- [x] Live fixture NNTP login, special-character credential preservation, Newznab repeat setup, service on/off and managed indexer disable.
- [ ] Real paid NNTP article retrieval/repair/decoding and AceStream engine/playback.

Evidence and exact limits: [optional sources validation](docs/OPTIONAL-SOURCES-VALIDATION.md). Earlier milestones above describe the versions tested at those times.

- [x] Preserve incoming native anime/EasyNews integrations with compatible-account gates, anime-only scoping, one EasyNews owner, and native manifest/schema acceptance.
- [ ] Measure incremental cached coverage and latency for optional Anime Tosho/nekoBT/TsukiHime; validate paid EasyNews search and playback.

- [x] Combined source `1bfec7b` passed fresh Linux image-only startup, 21 default endpoints, optional-service/NNTP and native preset acceptance, and strict routing/concurrency. The README now links its tested immutable bundle.
