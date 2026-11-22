# Docker Compose deployment and testing

## First installation

Run `docker compose up -d --build`, then open `http://SERVER:8088`. The portal
uses HTTP Basic authentication: username `admin`, password `ADDON_PASSWORD`
(default `admin`). Enter your server address, your debrid provider API key,
and optional metadata keys (TMDB, TVDB, MDBList).

The portal saves your configuration into `.env` safely (with concurrency locks and
scalar validation to prevent command injection), then launches the automated stack
provisioner (`stack-bootstrap`) to configure Prowlarr indexers, Posters+ rating
badges, AIOMetadata profiles, and the AIOStreams unified super-addon profile.

### Docker-engine access

The controller mounts the host Docker socket for setup; the portal also mounts it
for backup, restore and maintenance. Either container has effective Docker-engine
control. Keep the portal authenticated and on a trusted network.

### Port Exposure & Firewall Protection

By default, internal microservices (LumiereDB, Prowlarr, Zilean, StremThru, etc.)
bind their host ports to `127.0.0.1` using `INTERNAL_BIND_IP`. On a VPS or
unfirewalled host, Docker will not expose these internal scrapers to the public
internet. Only the two player ingress points are published externally:

- **Port 3001**: AIOStreams super-addon and media streaming
- **Port 4005**: AIOMetadata catalogs and poster rating overlays

If you run on a private LAN NAS (Unraid, TrueNAS, Synology) and want direct LAN
access to internal dashboards (e.g. Prowlarr UI), set `INTERNAL_BIND_IP=0.0.0.0`
in `.env`.

A manual recovery path or standalone setup run:

```sh
docker compose up -d
docker compose run --rm stack-bootstrap
```

Configuration values containing quotes, dollar signs or line breaks must be edited
directly in `.env` using Compose's dotenv syntax.

## Optional services

Public indexers are seeded into Prowlarr when reachable. External indexer uptime,
Cloudflare challenges and rate limits can affect results.

For Usenet, enter the server, port, username, password, TLS and connection count
on the setup page. Add Newznab indexer URL/API key pairs (e.g. altHUB, DrunkenSlug),
which are provisioned directly as native Newznab presets in AIOStreams (~250ms parallel searches),
keeping Prowlarr 100% dedicated to torrent indexers. Disabling Usenet stops its managed provider connections while retaining
credentials.

Torrentio is enabled by default (`ENABLE_TORRENTIO=true`). Set it to `false` to
omit it, or set `TORRENTIO_URL` to point to a custom endpoint. Additional optional
enrichments: `ENABLE_REMUXDB=true` (audio/video probe metadata), `ENABLE_DMM=true`
(Debrid Media Manager hashlist syncing via Zilean), and
`AIO_PRECACHE_NEXT_EPISODE=true` (background next-episode prefetch).

Jikan self-hosted anime metadata is optional; set `JIKAN_API_BASE` to use a local
instance instead of the public API.

Zilean's initial DMM import and AIOMetadata's initial caches create CPU, disk and
network load. Zilean limits are configurable in `.env`. All services have rotated
Docker logs (10 MB, three files).

## Repeatable tests

Use Docker Compose v2.24 or newer for the optional test configuration.

```sh
docker compose -p aio-tests -f compose.test.yml run --rm tests
docker compose -p aio-tests -f compose.test.yml run --rm browser-tests
docker compose -p aio-tests -f compose.test.yml run --rm database-test
docker compose -p aio-tests -f compose.test.yml down --volumes
```

Read-only provider authentication summaries:

```sh
docker compose -p aio-tests -f compose.test.yml run --rm providers
```

After the stack is running:

```sh
docker compose --profile test run --rm stack-check
```

The default stack checks 18 internal continuous services. TCP reachability is not
an application or playback guarantee.

## Updates and recovery

Back up `.env` and the complete `data/` directory. Keep `SECRET_KEY` unchanged for
existing profiles. Most upstream service images still use `latest`; validate
updates before deploying to your main host.

### Additional native sources

The setup page can enable Anime Tosho, nekoBT and TsukiHime for anime requests.
EasyNews direct search uses `EASYNEWS_USER`/`EASYNEWS_PASSWORD` from `.env` and
runs directly through AIOStreams. These sources are opt-in; paid EasyNews access
remains unverified.
