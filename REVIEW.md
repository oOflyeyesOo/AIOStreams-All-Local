# Copilot snapshot review — 2026-11-06

## Source and preservation

Reviewed `workspace-source-snapshot-20261107-050551.tar.gz` against GitHub main at `de8e4fd` in a separate `copilot-review` checkout. The snapshot contained 30 changed/new/deleted source paths relative to that baseline (the handoff estimated 31). The original archive is unchanged. Runtime database/cache directories were not imported into this checkout; the private `.env` remains ignored. No changes were committed or published, and the running production stack was not modified.

## Repairs made during review

- Profile download no longer contacts running services. Bootstrap still checks reachability when provisioning; exported configuration includes configured integrations without claiming that they are online. Downloads now build the payload before sending HTTP 200, so a failed build returns a proper 503 instead of mixed responses.
- Backup restore rejects symbolic links, hard links and special archive entries in addition to paths escaping the temporary extraction directory. Regression coverage verifies rejection before anything is restored.
- Docker unit tests shadow the live `.env` with `.env.example`. Bootstrap unit tests mock reachability explicitly, eliminating accidental network requests and slow DNS failures.
- Restored the four deleted PNGs from GitHub main. README still references the screenshots; deleting them breaks those illustrations. These are existing screenshots, not new screenshots of the modified UI.

## Verification completed

- Python regression suite: **72 passed in 0.895 seconds**, running in `python:3.11-alpine` through Compose. Initial run: 69 passed, one profile-download timeout; the first repaired run passed 71 tests in 85 seconds before network isolation was completed.
- Browser-settings suite: **6 passed** in `node:22-alpine` through Compose.
- PostgreSQL initialization: created all four databases and successfully repeated initialization against PostgreSQL 16.
- Compose validation: source, all-in-one and test definitions; core, scrapers, proxies, web, tunnel and all profiles passed using `.env.example`.
- Shared inventory check: 19 service names found in Compose. This validates names only, not listening ports or successful integrations.
- Private-value scan: no matches for distinct sensitive values from the local `.env` in tracked or unignored text source. This is a targeted scan, not a comprehensive historical secret audit.
- `git diff --check` passed. Test project `aio-copilot-tests` was removed after testing.

## Release blockers still present in the supplied source

1. **Setup cannot reliably apply new container settings.** Compose no longer defines `controller` or `stack-bootstrap` and does not pass `COMPOSE_CONTROL_SOCKET` to the portal. The fallback setup handler only runs the bootstrap script. Saving `.env` does not recreate containers, so services can retain their original keys/addresses. Restore the controller/bootstrap deployment wiring and verify an actual key/address change before release.
2. **Docker management-app installation was removed.** The committed baseline deleted `compose.manager.yml`, `scripts/generate_manager_compose.py`, `docker/packaged/`, deployment instructions and packaged-image tests; the snapshot additionally deletes the image-build workflow. This conflicts with the requested paste-and-deploy installation. Restoring old files alone is insufficient: packaged images must now include `init/service_inventory.py` and the new tools, and backup/resource operations need appropriate access to named-volume data and the Docker engine.
3. **Local Cinemeta service returned.** Compose, setup scripts, inventory and stack builder again deploy/check Hidden Cinemeta despite the prior request to retain only an external link. Remove the service consistently across installation paths.
4. **Debrid Search port regression needs live revalidation.** Current Compose, health checks, templates and inventory use internal port 3011. The previously tested deployment required container port 3001 with host port 3011. Verify the currently pulled image before correcting all references together.
5. **Full runtime acceptance remains outstanding.** No fresh full-stack startup, authenticated provider request, new profile provisioning, playback, UI screenshot refresh or manager-image build was performed in this review. Unit tests and Compose parsing do not establish those outcomes. Production remains untouched.

Copilot's portal diagnostics, shared inventory, backup tests and configuration validation are useful additions. Preserve them while resolving the deployment regressions; do not publish the snapshot as a fully tested release yet.
