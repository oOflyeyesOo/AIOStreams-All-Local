# Immutable releases and recovery

Manager deployments can use `compose.release.yml` and `release.lock.json` from a
successful **Build Docker manager images** workflow artifact. The lock pins the
nine packaged images and every upstream image by digest. The workflow starts that
exact set, checks internal endpoints and tests sequential stream routing before
uploading the bundle. Artifacts expire after 90 days; retain your installed bundle.

Paste the complete release Compose file into Portainer/Dockge, set a private
`ADDON_PASSWORD`, deploy, then enter keys on the portal. Keep the same project
name and named volumes on updates. The lock is also passed to the setup controller,
so clicking **Connect my stack** retains the pinned image set.

`compose.manager.yml` remains the rolling deployment option. A commit tag pins
packaged components only; it does not pin upstream services. Source and legacy
all-in-one deployments do not automatically become immutable releases.

## Preview, upgrade and rollback through Docker Compose

The operator helper requires a checkout, Docker Compose and Docker-engine access;
Python is provided in its container. Run it from the checkout directory. Download
the current and target bundles into `releases/current` and `releases/next`.
Keep any host settings in a Git-ignored `operator.env`, with the same project name,
ports and portal password as the installed stack. Saved provider keys stay in its
configuration volume and are reapplied by the controller.

Current AIOStreams uses an explicit configuration access key, derived from the
portal password. Bootstrap supplies it for configuration writes. Change the password
through the deployment settings and reapply setup before making further profile
changes; existing media URLs are not a substitute for configuration-write access.

```sh
docker compose -f compose.tools.yml run --build --rm release-tools preview releases/current/release.lock.json releases/next/release.lock.json

docker compose -f compose.tools.yml run --rm release-tools upgrade --project aio-local --env-file operator.env --current releases/current/compose.release.yml --target releases/next/compose.release.yml --backup-dir .private-upgrades/next

docker compose -f compose.tools.yml run --rm release-tools rollback --project aio-local --env-file operator.env --state .private-upgrades/next/upgrade-state.json
```

Preview lists image changes and removed services. Download sizes and migration
compatibility are not inferred from tags; review upstream release notes. Upgrade
creates a fresh backup, checks PostgreSQL, configuration and the saved AIOStreams
profile, hashes the archive, then pulls all target images before replacing services.
Startup or controller failure produces a failed state, never a success message.

Rollback is explicit: it verifies the backup hash and project, stops applications,
restores the snapshot with the previous tooling image, and starts the previous
image set. Stale SQLite journals are removed before replacing SQLite snapshots.
Do not remove named volumes or prune previous images during recovery. Backups
contain credentials and personal configuration: protect the entire private
recovery directory and never upload it with a release.

This is an offline snapshot restore, not a guarantee that every upstream migration
is reversible. Stop other writers and take a host/volume snapshot for major database
upgrades. Restoring older archives without SQL/profile coverage cannot satisfy the
upgrade gate. Legacy archives remain available to the separate restore command,
with their original limitations. Restore separately managed PostgreSQL roles or
grants before relying on a custom-role deployment; the supported dump deliberately
does not recreate the server's global role catalog.

## Acceptance evidence

Disposable project `aio-package` was exercised with two distinct immutable local
bootstrap image versions, named volumes, a saved profile and a SQL sentinel:
upgrade retained identity/data, rollback recovered the pre-upgrade sentinel, and
an intentionally invalid release lock failed and recovered through rollback.
This tests the recovery machinery; it is not evidence for arbitrary upstream
database-version downgrades. Provider keys were blank throughout. The retained
installation and original workspace archive were not changed.

The current [tested bundle](https://github.com/oOflyeyesOo/AIOStreams-All-Local/actions/runs/42454737222/artifacts/13607288027) is source `1bfec7b543b6a9197d3a9eedb19a40b1f040c01f`. It passed fresh Linux startup, 21 default endpoint checks, optional-service and fixture NNTP acceptance, native preset validation and strict routing/concurrency checks. [Machine-readable evidence](validation/2026-11-08-linux-release.json) records its artifact digest and boundaries.
