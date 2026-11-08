# Docker Compose deployment and testing

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

### Docker-engine access
The controller mounts the host Docker socket for setup; the portal also mounts it
for backup, restore and maintenance. Either container has effective Docker-engine
control. The controller exposes a restricted local setup API, but that does not
reduce the power of its socket mount. Keep the portal authenticated and on a
trusted network. Moving maintenance behind controller actions remains planned.

### Port Exposure & Firewall Protection
By default, internal microservices (Comet, Prowlarr, MediaFusion, Sootio, Zilean,
StremThru, MediaFlow, etc.) bind their host ports to `127.0.0.1` using `INTERNAL_BIND_IP`.
On a VPS or unfirewalled host, Docker will not expose these internal scrapers to the public
internet. Only the two player ingress points are published externally:
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
Compose's dotenv syntax; Usenet username/password fields handle quotes and dollar signs safely; other portal fields reject these values rather than allowing
newline/interpolation injection. The old dashboard URL redirects
to the new setup screen.

## Optional services

Public indexers are seeded into Prowlarr when reachable. External indexer uptime,
Cloudflare challenges and rate limits can affect results. Provider credentials
alone do not guarantee a paid account has the required entitlement.

MediaFusion is off by default. Enable it on the setup page, optionally supplying a configured manifest for its extra integrations. The switch starts or stops its container and retains its data. Required external engines/accounts are not installed automatically.

For Usenet, enter the server, port, username, password, TLS and connection count on the setup page. Add a Newznab base URL/API key, or use your existing Prowlarr indexers. Connect my stack configures InfiniDysk and one Usenet-only native AIOStreams route automatically. Passwords stay hidden on reload; leaving the saved-password field blank preserves it. Disabling Usenet stops its managed provider connections and indexer polling while retaining credentials. The form replaces InfiniDysk's provider list when enabled. Unmanaged JSON/UI settings remain supported.

Native Torrentio is enabled for debrid configurations and is not repeated inside Sootio or MediaFusion. Set `ENABLE_TORRENTIO=false` to omit it. `KNIGHTCRAWLER_URL` optionally replaces its endpoint; it does not add a container. Background next-episode searches are opt-in through `AIO_PRECACHE_NEXT_EPISODE=true`.

[Measured source coverage and fixture NNTP acceptance](docs/OPTIONAL-SOURCES-VALIDATION.md) distinguish authentication/indexer tests from unverified paid article playback.

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

The default stack checks 21 internal endpoints (22 with MediaFusion enabled). TCP reachability is not an application or playback guarantee.
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

### Additional native sources

The setup page can enable Anime Tosho, nekoBT and TsukiHime for anime requests.
Compatible accounts are selected automatically; unsupported sources stay disabled.
They are opt-in while incremental coverage and timing acceptance remains pending.
EasyNews direct search uses `EASYNEWS_USER`/`EASYNEWS_PASSWORD` from the private
`.env`, and runs once through AIOStreams rather than through Sootio as well.
Native schemas/manifests passed fixture checks; paid EasyNews access remains unverified.
