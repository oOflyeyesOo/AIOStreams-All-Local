# Added-feature validation — 2026-11-07

Tests use disposable Docker projects; the existing installation, original backup and provider keys are untouched. No real provider keys were added back to development files.

| Feature | Verified behavior | Limits |
|---|---|---|
| Backup/restore | Real PostgreSQL dump/drop/restore and SQLite sentinel recovery; actual portal download contains PostgreSQL, Prowlarr DB and current settings | Existing services should be stopped before restoring into their databases; custom PostgreSQL roles must already exist |
| Backup download | Authentication, no-store header, repeated downloads reflect modified settings, unique/atomic archive publication | Backups intentionally contain the operator's saved secrets; protect downloaded archives |
| Cache cleanup | Dry run, real disposable-volume deletion, POST-only access, origin rejection, escaping symlinks blocked, databases/config preserved during poster cleanup | No cleanup performed in original installation |
| Resources | Live metrics scoped to all 22 package-project containers; Docker failures; real host memory used rather than largest container limit | Docker socket access required |
| Updates | Bash and PowerShell syntax and injected failure at each of four Docker stages; no false success or host-wide image pruning | No forced live version upgrade or migration of original installation |
| Tracking | Installed upstream code inspected; correct client credentials wired; existing OAuth records preserved on repeat setup; missing credentials rejected | Real Trakt/Simkl/AniList consent, refresh and watchlist/scrobble remain unverified without accounts |
| Tunnel | Disabled in default manager profile; missing credentials rejected; explicit tunnel profile validates | External DNS/TLS/routing and an authenticated tunnel require operator's tunnel token |

## Bugs corrected

- Prowlarr's database was missing from backups, losing configured indexers on restore.
- SQL restore could report success after PostgreSQL errors; failed cluster restore also returned overall success.
- Restoring pg_dumpall could collide with the currently connected default role. New snapshots dump application databases with no role recreation.
- Concurrent backups could overwrite the same second-based filename or expose partially written archives; archives now publish atomically under unique names.
- Portal could reuse a stale backup for five minutes after settings changed; every requested backup now captures current settings.
- Poster cleanup deleted the whole volume, including databases/configuration; now only image files are removed.
- Cache symlinks could escape the requested workspace, and deletion failures could be reported as successful cleanup.
- GET requests could trigger cache deletion; cleanup now requires authenticated POST with origin checks.
- PowerShell update ignored failed native-command exit codes. Updates now stop at the failed stage.
- Update verification used a fixed container name and host-wide image pruning. It now runs the Compose stack-check and leaves unrelated images alone.
- Resource monitor inferred host RAM from container limits; now reads Docker host memory directly.
- Trakt's client-secret input was missing.
- Simkl client IDs and raw AniList tokens were passed as saved OAuth token-record IDs. Those are now created through AIOMetadata's authorization flow.
- Repeating metadata setup could overwrite linked accounts. Existing configuration is loaded first; a failed load stops the update.

## Reproduce

- Regression suite: `docker compose --env-file .env.example -p aio-tests -f compose.test.yml run --rm tests`.
- PostgreSQL destructive test: `tests/check_backup_restore_live.py`, only with `AIO_PROJECT_NAME=aio-feature-tests` and its separate fixture PostgreSQL container.
- Portal live tests: `tests/check_features_live.py`, only inside the disposable `aio-package` portal.
- Update failures: `tests/check_update_scripts.py` (Bash environment, source mounted at `/src`) and `tests/check_update_scripts.ps1` (PowerShell from repository root).
- Real-user OAuth is performed at the AIOMetadata configure link after entering app credentials and rerunning setup. Legacy `ANILIST_TOKEN` is not treated as a database token-record ID.

PostgreSQL/SQLite restore and live portal backup/cache/resource tests passed. Linux and Windows update failure tests passed. Regression count and CI status are reported in the release summary.


Real metadata save/load/update was repeated successfully with an explicitly non-live TMDB fixture string; the resulting manifest returned HTTP 200. This checks API contracts and idempotence, not TMDB authentication or account authorization. With no metadata key, setup correctly rejected the save. CI now repeats both update-script failure tests and the destructive fixture database restore.
