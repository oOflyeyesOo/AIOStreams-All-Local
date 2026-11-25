# AIO Local — status and roadmap

See the [November 25 audit & 24/7 stability roadmap](docs/DEVELOPMENT-ROADMAP.md#deep-dive-247-stability-security--missing-links-roadmap--november-25-2026) for the current
review, verified findings, and active implementation plan. Status below is historical.

Updated 2026-11-17. Goal: deploy through Docker Compose or a management app,
enter keys on one page, receive manifests for compatible players.

## Current status

- Source and prebuilt manager deployments working; 6 packaged images published.
- Movie and episode HTTP range reads and 15-second media decode verified.
- Immutable release/recovery, backup/restore, and upgrade-rollback paths tested.
- 123 Python tests, 12 browser checks, and source release CI passing.
- Native Torrentio, RemuxDB, DMM, Usenet (Native Engine & Newznab Direct), and EasyNews integrations
  present; real paid NNTP decoding and ARM/NAS compatibility remain unverified.

## What's next

- **Setup UX**: guide users from tracking-app credentials to upstream account
  connection; show connected/disconnected status clearly.
- **OAuth lifecycle**: real consent, token refresh, expiry, reconnect and
  revocation for Trakt, Simkl, and AniList.
- **Remote access**: verify authenticated tunnel/reverse-proxy paths (public
  manifest URLs, metadata, subtitles, CORS, range requests).
- **Cold-search performance**: bound cold searches, measure warm/cold timings and
  request counts on a documented reference host.
- **Platform matrix**: repeat clean install and upgrade on a Linux server and at
  least one NAS/management-app environment; document ARM64 blockers.

## Working rules

1. Complete one milestone's acceptance checks before broadening its claims.
2. Use disposable projects and fixture data for destructive tests; preserve the
   existing installation and original backup.
3. Keep live credentials, OAuth tokens, signed media URLs and runtime data out of
   Git, images, logs and screenshots.
4. Attach regression coverage to concrete bugs; repeat live checks when the
   affected deployment path changes.
5. Keep one generated manager definition aligned with source Compose; validate
   both in CI.
