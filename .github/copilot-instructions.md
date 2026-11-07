# Copilot instructions for AIOStreams-All-Local

## Project shape

This repository is a Docker Compose appliance rather than a conventional single-language application. The root Compose stack wires roughly 20 upstream and local services onto the private `stremio-net` network:

- **Portal and orchestration:** `docker/all-in-one/portal_server.py` serves the setup UI on port 8088, validates/authenticates API requests, safely updates `.env`, reports integration health, and starts provisioning.
- **Provisioning:** `init/bootstrap/setup_stack.py` waits for optional services, configures Prowlarr/MediaFusion/AIOMetadata/AIOStreams, builds the local AIOStreams profile from `templates/`, pre-seeds Stremio Web, and runs manifest/stream diagnostics.
- **Runtime services:** `docker-compose.yml` defines AIOStreams, scrapers, indexers/cache, metadata/artwork, subtitles, proxies, players, and shared PostgreSQL/Redis. Most services are upstream images configured through environment variables; local Python/JS code is concentrated in the portal, bootstrapper, entrypoints, and web-player bootstrap.
- **Configuration data:** `templates/` contains JSON setup profiles, formatters, filtering expressions, regex rankings, and metadata presets. Treat template IDs and manifest URLs as integration contracts.
- **Frontend/player assets:** `index.html`, `dashboard.html`, `assets/`, and `docker/stremio-web/bootstrap.js` provide the setup UI and browser/player behavior. `docker-compose.aio.yml` is the separately packaged all-in-one image path.

The public architecture intentionally exposes AIOStreams on port 3001 and AIOMetadata on port 4005. Internal scrapers, indexers, databases, proxies, and player services normally bind to `INTERNAL_BIND_IP` (default `127.0.0.1`) and communicate by Docker service name. PostgreSQL database creation is gated by `init-postgres`; Redis health gates dependent services.

## Build, run, and validation commands

Docker Compose v2.24+ is expected for the test configuration. The normal local setup is:

```sh
cp .env.example .env       # or run the setup wizard
./setup.sh start core      # lean profile
./setup.sh start           # default/all services
docker compose up -d --build
```

Useful management commands are exposed by `setup.sh`: `./setup.sh check`, `status`, `stop`, `links`, `test`, `benchmark`, `backup`, `restore`, `update`, `clean-cache`, `resources`, and `build`.

Validate Compose files and every supported profile as CI does:

```sh
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example -f docker-compose.aio.yml config --quiet
docker compose --env-file .env.example -f compose.test.yml config --quiet
for profile in core scrapers proxies web tunnel all; do
  docker compose --env-file .env.example --profile "$profile" config --quiet
done
```

Run the CI regression suites:

```sh
docker compose -p aio-tests -f compose.test.yml run --rm tests
docker compose -p aio-tests -f compose.test.yml run --rm browser-tests
docker compose -p aio-tests -f compose.test.yml run --rm database-test
docker compose -p aio-tests -f compose.test.yml down --volumes
```

Run one Python test by fully-qualified unittest name:

```sh
docker compose -p aio-tests -f compose.test.yml run --rm tests \
  python3 -m unittest tests.test_portal.PortalTests.test_server_address_normalization
```

Run one browser test by Node test-name pattern:

```sh
docker compose -p aio-tests -f compose.test.yml run --rm browser-tests \
  node --test --test-name-pattern="signed-in profile stays unchanged" tests/browser-bootstrap.test.cjs
```

After the full stack is running, use the live probes when the change affects service wiring or playback:

```sh
docker exec aio-portal python3 /app/tests/check_all_services_e2e.py
docker exec aio-portal python3 /app/tests/check_playback.py
docker compose --profile test run --rm stack-check
```

There is no separate repository lint/format command or package manifest. For Python changes, use the existing `unittest` suites; for browser bootstrap changes, use Node’s built-in `node:test` suite.

## Repository-specific conventions

- Keep secrets in the ignored `.env`; use `.env.example` for defaults/documentation. Never print provider keys, passwords, tokens, encrypted manifest credentials, or credential-bearing URLs. The portal returns configured-key indicators rather than secret values, and the bootstrapper redacts secrets from logs.
- Preserve the portal’s safe configuration behavior: validate scalar values before writing, reject newline/interpolation injection, serialize concurrent writes, and write through a temporary file followed by `os.replace`. Do not bypass these helpers with ad hoc `.env` writes.
- Preserve URL derivation rules. `BASE_URL` drives public service URLs; remote deployments derive `aiometa.<domain>` for AIOMetadata, while local/private hosts use port 4005. Explicit non-placeholder service URLs must not be overwritten during portal saves.
- Provisioning is intentionally best-effort for services excluded by the selected Compose profile, but required dependencies and invalid manifests must fail visibly. Keep health checks distinct from manifest readiness and preserve the `depends_on` conditions when changing service definitions.
- AIOStreams configuration is assembled from local template JSON and internal Docker URLs, then exposed through both the canonical personalized manifest and the stable `/stremio/u/local/manifest.json` alias. Changes to template IDs, service IDs, or manifest paths require updating bootstrap diagnostics and relevant tests together.
- Use Compose profiles consistently: `core`, `scrapers`, `proxies`, `web`, `tunnel`, and `all` select optional services. Internal host ports should remain loopback-bound by default; only the two remote ingress ports are intended for public exposure.
- Shared PostgreSQL is initialized by `init/postgres/init-databases.sh`/`01-init-dbs.sql`; changes to database names or initialization order must preserve repeat-safe startup because CI runs the initializer twice.
- The browser bootstrap must preserve signed-in Stremio profiles and existing guest preferences/addons, while only seeding the local addon for eligible guests. Keep its behavior covered by `tests/browser-bootstrap.test.cjs`.
- Prefer the existing standard-library implementations and Docker images over adding dependencies. Keep Python compatibility with the `python:3.11-alpine` test/runtime containers and use POSIX shell syntax in setup scripts.
