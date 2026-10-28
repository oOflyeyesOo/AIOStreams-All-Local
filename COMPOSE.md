# Docker Compose deployment and testing

For Portainer/Dockge and other stack editors, use the prebuilt-image
[manager deployment](DEPLOYMENT.md) and `compose.manager.yml`. The instructions
below describe the checkout-based source deployment.

## First installation

Run `docker compose up -d --build`, then open `http://SERVER:8088`. The portal
uses HTTP Basic authentication: username `admin`, password `ADDON_PASSWORD`
(default `admin`). Enter your server address, your debrid provider API key,
and optional metadata keys (TMDB, TVDB, MDBList).

The portal saves your configuration into `.env` safely (with concurrency locks and
scalar validation to prevent command injection), then launches the automated stack
provisioner (`stack-bootstrap`) to configure Prowlarr indexers, MediaFusion admin
credentials, Posters+ rating badges, AIOMetadata profiles, and the AIOStreams
unified super-addon profile.

### Applying saved settings
The setup controller mounts the host Docker socket to apply container settings.
This gives it Docker-engine authority. Only the controller mounts that socket;
the authenticated portal submits setup actions through a local Unix socket.
The controller operates on its own Compose project using the saved definition.
Keep the portal accessible only to trusted administrators.

### Port Exposure & Firewall Protection
By default, internal microservices (Comet, Prowlarr, MediaFusion, Sootio, Zilean,
StremThru, MediaFlow, etc.) bind their host ports to `127.0.0.1` using `INTERNAL_BIND_IP`.
On a VPS or unfirewalled host, Docker will not expose these internal scrapers to the public
internet. The portal on port 8088 and these two player ingress points are published:
- **Port 3001**: AIOStreams super-addon and media streaming
- **Port 4005**: AIOMetadata catalogs and poster rating overlays

If you run on a private home LAN NAS (Unraid, TrueNAS, Synology) and want direct LAN
access to internal dashboards (e.g. Prowlarr UI), set `INTERNAL_BIND_IP=0.0.0.0` in `.env`.

No further Docker commands are required for normal key or address changes through
the wizard. A manual recovery path or standalone setup run is:

```sh
docker compose up -d
docker compose run --rm stack-bootstrap
```

Configuration values containing
quotes, dollar signs or line breaks must be edited directly in `.env` using
Compose's dotenv syntax; the portal rejects these values rather than allowing
newline/interpolation injection. The old dashboard URL redirects
to the new setup screen.

## Optional services

Public indexers are seeded into Prowlarr when reachable. External indexer uptime,
Cloudflare challenges and rate limits can affect results. Provider credentials
alone do not guarantee a paid account has the required entitlement.

InfiniDysk accepts a single INFINIDYSK_USENET_PROVIDERS JSON object. The example
format is in `.env.example`. Leave it blank to configure providers through its UI.
The legacy USENET_HOST/USER/PASS fields do not configure its current headless
schema. Usenet playback needs a provider and NZB indexers; it was not end-to-end
tested in this environment.

Zilean's initial DMM import and AIOMetadata's initial caches create CPU, disk and
network load. Zilean limits are configurable in `.env`. Measure the host before
changing them. All services have rotated Docker logs (10 MB, three files).
Redis readiness gates its long-form dependents; database initializer errors now
block services that require completed database setup.

## Repeatable tests

Use Docker Compose v2.24 or newer for the optional test configuration. Its
PostgreSQL test uses temporary storage, no host database directory and no
published ports. The tests do not require paid provider keys.

```sh
docker compose -p aio-tests -f compose.test.yml run --rm tests
docker compose -p aio-tests -f compose.test.yml run --rm browser-tests
docker compose -p aio-tests -f compose.test.yml run --rm database-test
docker compose -p aio-tests -f compose.test.yml down --volumes
```

The Python tests cover portal authentication, private-file protection, safe and
concurrent saves, setup/export behavior, metadata API authentication, false
readiness responses, error stream entries, and database/entrypoint failures.
The JavaScript suite checks the player's guest setup and preservation of signed-in
profiles. The real PostgreSQL test checks first creation and repeat initialization.
GitHub Actions runs these on pushes and pull requests.

Read-only provider authentication summaries use the Git-ignored `.env`:

```sh
docker compose -p aio-tests -f compose.test.yml run --rm providers
```

After the stack is running:

```sh
docker compose --profile test run --rm stack-check
```

This checks HTTP/manifest endpoints for nine services and TCP availability for
fourteen others. TCP reachability is not an application or playback guarantee.
The optional check_playback.py probe requests at most 1 KB of a returned stream
and never prints credential-bearing links. It is a diagnostic, not a decoder test.

## Updates and recovery

Back up `.env` and the complete `data/` directory. Keep SECRET_KEY unchanged for
existing profiles. Most upstream service images still use `latest`; validate
updates before deploying them to your main host. Anime Kitsu's build is pinned to
a verified revision and its optional Fanart patch fails if the source changes.

For returning Stremio Web browsers, accept its user-interface update banner when
shown. The startup loader versions its app shell, preserves signed-in accounts
and adds the local aggregator to a guest profile. A browser that previously
loaded a broken test configuration may need its test-only site data cleared.
