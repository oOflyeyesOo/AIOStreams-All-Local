# Final release roadmap

Copilot's original roadmap is preserved in [docs/COPILOT-ROADMAP.md](docs/COPILOT-ROADMAP.md). We retain its repeatable setup, secret protection, backup/restore, pinned builds, negative tests and acceptance matrix. The original product direction remains: one page, Compose or manager deployment, enter keys, receive an installable manifest.

## Release gates (in order)

1. **Deployment recovery — in progress.** Restore controller/bootstrap and packaged manager images; retain diagnostics, shared inventory and tested archive protections. Remove local Cinemeta consistently. Restore first-visit web-player bootstrapping. Generated manager configuration must match source.
2. **Single-owner routing — in progress.** Comet owns Prowlarr and Zilean; Prowlarr owns its public indexers. Sootio owns its distinct direct sources, never recursively calls Comet/Torrentio/StremThru/Zilean. MediaFusion serves its own database without querying those sources again. Metadata, subtitle and library addons advertise only their intended resources. Deduplicate returned hashes/files separately. Proxies are transport choices, not extra scrapers.
3. **Fresh deployment — pending.** Start an isolated complete stack with fresh data, original provider keys and separate host ports. Test setup twice, configuration updates, canonical and alias manifests, each service's actual HTTP behavior and failed-dependency reporting.
4. **Playback and request audit — pending.** Movie and episode stream lookup, provider resolution, HTTP range reads and media decode; verify repeated-request behavior and service call counts. A healthy container or 1 KB response alone is not a playback pass. Record unavailable external sources and missing optional credentials as unverified, never passed.
5. **Data lifecycle and packaging — pending.** Disposable backup/restore, package builds, generated Compose validation, source/manager parity, tested image references and rollback notes. No live keys in source, reports, screenshots or images.
6. **Release — pending.** Refresh README/screenshots, record exact evidence and limitations, rerun regression suites, publish to main and verify CI/images. Do not describe a partial live test as a final release.

## Supported test scope

Premiumize is the primary live provider because that is the account supplied. TMDB, TVDB and Fanart use supplied configuration when valid. Other debrid accounts, NNTP, tracking OAuth and public TLS endpoints require their own credentials/infrastructure; test their missing-configuration behavior and label live verification unavailable until provided.

## Evidence

Previous review: 72 Python tests, 6 browser tests and repeated database initialization passed. The review's manager/controller/Cinemeta findings are being resolved here. Direct inspection of the current Debrid Search image confirmed port **3011** (3001 closed), correcting the earlier port concern. Final results will be recorded in `docs/RELEASE-VALIDATION.md`.


Latest evidence: all eight local package images build; complete image-only stack passes 21 endpoint checks; portal/controller apply completes; 77 regression tests pass. Live movie and episode decode passed before key removal. Current source and development configurations are cleared of supplied keys; Git history key removal is authorized; the original installation and backup remain unchanged. Publication follows final checks and history sanitization.
