# AIO Local

[![Microservices](https://img.shields.io/badge/microservices-19%20running-success?logo=server&logoColor=white)](#-what-is-integrated)
[![Regression Tests](https://img.shields.io/badge/regression%20tests-123%20passed-brightgreen?logo=checkmarx&logoColor=white)](#-automated-testing--verification)
[![Remote Streaming](https://img.shields.io/badge/remote%20streaming-ports%203001%20%26%204005-blueviolet?logo=cloudflare&logoColor=white)](#-remote-playback--dual-subdomain-architecture)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A 100% self-hosted Docker Compose streaming backend centered on **AIOStreams**. Enter your provider keys in one setup screen, let the stack wire all 19 bundled continuous services (14 applications + databases & supervisor) together on your private Docker network (stremio-net), and copy your personalized manifest URLs directly into Stremio or any compatible player.

The portal can configure a Usenet provider and a Newznab indexer from input fields. Torrentio runs once through AIOStreams for additional coverage; [source comparisons and Usenet acceptance](docs/OPTIONAL-SOURCES-VALIDATION.md) explain the measured benefits and limits.

Torrentio is an external addon. Its native integration includes enabled provider credentials in its configured addon URL; set ENABLE_TORRENTIO=false to disable it. Treat personalized manifests and profile exports as private.


The interface is one page: keys, setup progress, the main AIOStreams manifest, an optional standalone metadata manifest, service health and maintenance. Installing both manifests can duplicate catalogs.



For reproducible deployments, use the [digest-pinned release bundle and recovery guide](docs/IMMUTABLE-RELEASES.md). See the [end-to-end streaming path & transport guide](docs/STREAMING-PATH.md), the [anime ecosystem & profile guide](docs/ANIME-AND-PROFILES.md), and the [request ownership map](docs/ROUTING-VALIDATION.md) for detailed architecture, proxy shielding, anime capabilities, and tested limits.



[Download the tested Compose release bundle](https://github.com/oOflyeyesOo/AIOStreams-All-Local/actions/runs/43020613160/artifacts/13855052857) for management-app deployment. This release passed a fresh Linux install with zero first-start AIOStreams restarts, Usenet setup tests, native preset validation and strict routing/concurrency checks. Extract the archive and use its `compose.release.yml`; retain its lock file for upgrades.



---



## 📸 Visual Previews & Screenshots



### 1. Unified Setup & Manifest Generator (`:8088` / `index.html`)

> Saved-key indicators, automatic service configuration, and dual personalized takeaway manifests for AIOStreams and AIOMetadata.



<p align="center">

  <img src="assets/setup-desktop.png" alt="AIO Local desktop setup and manifests" width="100%">

</p>



### 2. Live Integration Status (`:8088#integrations`)

> All bundled application services grouped by purpose with real-time connection checks and database handshakes.



<p align="center">

  <img src="assets/integrations.png" alt="AIO Local integration status" width="100%">

</p>



### 3. Responsive Mobile Experience

> Clean, responsive design for easy setup and direct manifest installation on iOS, Android, and tablets.



<p align="center">

  <img src="assets/setup-mobile.png" alt="AIO Local mobile setup" width="45%">

</p>



---



### Readiness and maintenance



Configuration, authorization and playback are labeled separately. Resource use,

backup coverage, search activity and confirmed cache cleanup stay on the same page.

These screenshots use a disposable stack with no provider keys.



![Desktop maintenance](assets/maintenance-desktop.jpg)



<img src="assets/maintenance-mobile.jpg" alt="Mobile maintenance with missing keys clearly labeled" width="390">



## 🔒 Remote Playback & Dual Subdomain Architecture



For remote playback, route these two endpoints through your reverse proxy or tunnel. Keep the portal and other published dashboards on a trusted network, and review the actual Compose port bindings:

1. **AIOStreams (`aio.yourdomain.com` ➔ Port 3001)**: Aggregates streams, queries local scrapers, proxies requests through `BuiltinProxy`, and handles Debrid CDN stream handoffs.

2. **AIOMetadata (`aiometa.yourdomain.com` ➔ Port 4005)**: Serves rich catalogs (Netflix, Prime, Disney+, Apple TV+, Max, Anime) and poster artwork badges directly to players anywhere in the world.



All other microservices (Comet, Zilean, Prowlarr, Posters+, SubSense, Postgres, Redis, etc.) remain strictly internal to the Docker network (`stremio-net`) and bind to loopback (`127.0.0.1`) on the host.



```mermaid

flowchart LR

    Player["📱 Stremio / Nuvio Player<br/>(Outside Home Network)"]

    

    subgraph Ingress ["☁️ Cloudflare Tunnel / Reverse Proxy"]

        TunnelAIO["aio.yourdomain.com<br/>(Port 3001)"]

        TunnelMeta["aiometa.yourdomain.com<br/>(Port 4005)"]

    end



    AIO["⚡ AIOStreams (:3001)<br/>BuiltinProxy (FORCE_PROXY_ENABLED)"]

    AIOMeta["🎨 AIOMetadata (:4005)<br/>Catalogs & Overlays"]

    

    subgraph Internal ["🔒 Private Local Network (stremio-net)"]

        direction TB

        Comet["Comet (:8000)"]



        Zilean["Zilean DMM (:8181)"]

        Prowlarr["Prowlarr (:9696)"]

        Posters["Posters+ (:9039)"]

        SubSense["SubSense (:3100)"]

        DB[("PostgreSQL & Redis")]

    end

    

    CDN["🚀 Debrid CDN<br/>(Real-Debrid / Premiumize)"]



    Player -->|1a. Stream Request| TunnelAIO

    Player -->|1b. Catalog / Poster Request| TunnelMeta

    

    TunnelAIO -->|Port 3001| AIO

    TunnelMeta -->|Port 4005| AIOMeta

    

    AIO -->|2. Internal Scrape| Comet

    AIOMeta -->|Internal Poster Cache| Posters

    Comet -->|3. Torrent/Cache Lookup| Zilean & Prowlarr & DB

    AIO -->|4. Resolve & Follow 302 Redirect| CDN

    AIO -->|5. HTTP 206 Partial Content Stream| Player

```



* **Internal Loopback Binding (`INTERNAL_BIND_IP=127.0.0.1`)**: Internal scrapers, indexers, and proxies bind to `127.0.0.1` on the host, preventing unauthenticated access from the public internet even on a VPS where Docker bypasses UFW. For private home LAN NAS deployments needing direct LAN dashboard access, set `INTERNAL_BIND_IP=0.0.0.0` in `.env`.

* **Built-in Stream Proxying**: AIOStreams' `BuiltinProxy` intercepts stream requests and transforms scraper links (e.g. `http://comet:8000/...`) into secure proxy endpoints (`${BASE_URL}/api/v1/proxy/...`).

* **Debrid CDN Redirect Handling**: When playing media, AIOStreams follows the provider's 302 redirect internally and streams video bytes directly to your player over HTTP 206 Partial Content.



---



## 🚀 Quick Start

### Option A: 1-Command Appliance (`docker run` — Recommended)

Run the entire self-hosted stack (Portal, AIOStreams, Scrapers, Indexers, Debrid Cache, and Web Players) inside a single container with zero configuration files needed:

```bash
docker run -d \
  --name aio-stack \
  --pull always \
  --privileged \
  --restart unless-stopped \
  --label port=8088 \
  -p 8088:8088 \
  -p 3001:3001 \
  -p 4005:4005 \
  -p 8082:8082 \
  -p 8085:8085 \
  -v aio-data:/data \
  ghcr.io/ooflyeyesoo/aiostreams-aio:latest
```

* **Primary Web Portal (`:8088`)**: Open **`http://YOUR-SERVER-IP:8088`** to configure your provider keys, run automated health checks, test playback, and copy your personalized manifests. Local portal access is password-free by default.
* **Why `--label port=8088`?** By default, container dashboards, reverse proxies, and local service discovery tools sort port mappings numerically (`3001` < `8088`), inadvertently launching AIOStreams instead of the setup portal. `--label port=8088` is the universal, vendor-neutral label that instructs container discovery tools to treat port `8088` as the primary web entrypoint.
* **Port Reference**:
  * `8088`: Web Setup Portal & Diagnostic Center (Primary UI)
  * `3001`: AIOStreams Core Addon Aggregator (Manifest URL & Stream Engine)
  * `4005`: AIOMetadata Catalogs & Streaming Badges (Standalone Manifest)
  * `8082`: Stremio Web Player
  * `8085`: Nuvio Web Player
  *(All backend scrapers, indexers, proxies, and databases communicate securely inside the container and require no host ports).*

### Option B: Docker Compose

For traditional multi-container Docker Compose management:

```sh
./setup.sh start
```

### 2. Configure via Setup Portal

Open **`http://YOUR-SERVER:8088`**:
1. Set your server addresses:
   - **AIOStreams address**: `https://aio.yourdomain.com` (or `http://localhost:3001` for local play)
   - **AIOMetadata address**: `https://aiometa.yourdomain.com` (or `http://localhost:4005`)
2. Enter your streaming provider key (Real-Debrid, Premiumize, TorBox, AllDebrid, Debrid-Link, EasyDebrid, Offcloud, Seedr).
3. Enter your metadata keys (TMDB, TVDB, Fanart, MDBList).
4. Click **Connect my stack**.

The portal automatically saves `.env` safely, provisions indexers and databases, configures AIOMetadata presets with Posters+, and activates the AIOStreams super-addon profile. Once complete, copy the manifest URLs directly into your player.



After entering provider and metadata keys, use **Download optimized profile

JSON** in the portal to retrieve the generated AIOStreams profile. This is the

same optimized configuration used by bootstrap; the download is authenticated

and contains the configured provider credentials, so keep it private.



For monitoring and reverse-proxy health checks, the portal exposes:



- `/healthz` — portal process is responding.

- `/ready` — the AIOStreams dependency is responding.

- `/manifest-ready` — the local AIOStreams manifest has an ID and stream resources.

- `/api/diagnostics` — authenticated, credential-redacted core-path diagnostics.

- `/version` — current portal version.



### 3. Automation and maintenance commands



The repository includes a portable `Makefile` for non-interactive validation and

maintenance. These commands use the same Compose files as the Linux and

Windows management scripts:



```sh

make validate

make test

make build

make backup

make restore ARCHIVE=/path/to/aio-backup.tar.gz

make integrations       # report configured optional adapters without secrets

make e2e                 # requires a running aio-portal container

```



Use `./setup.sh` or `setup.ps1` for interactive startup, profile selection,

status, updates, resource monitoring, and cache cleanup.



---



## 🎛️ Stack Profiles & Configuration Templates

Modular Docker Compose profiles allow you to scale your deployment from a lean, ultra-light setup on low-resource machines to the complete 19-container appliance (14 integrated applications + databases & supervisor):

### 1. Docker Compose Resource Profiles

| Profile | Launch Command | RAM Usage | Included Services & Description |
| :--- | :--- | :--- | :--- |
| **`scrapers`** (Default Complete) | `docker compose --profile scrapers up -d` | **~2.8 GB** | Complete streaming appliance with all scrapers, indexers, proxies, Usenet, Stremio Web, SlickSync, and Anime Kitsu (everything except Nuvio). |
| **`core`** (Ultra-Lean) | `docker compose --profile core up -d` | **~1.1 GB** | Fast, minimal Debrid stack: AIOStreams, Comet, AIOMetadata, Posters+, SubSense, PostgreSQL 16, Redis 7, Search Broker, and Portal. Ideal for low-memory VPS. |
| **`nuvio`** (Dedicated Player) | `docker compose --profile nuvio up -d` | **~250 MB** | Standalone Nuvio Web Player (`:8085`) with full features, AniSkip, IntroDB, and admin dashboard (`/admin`). Combine via `COMPOSE_PROFILES=scrapers,nuvio`. |
| **`all`** | `docker compose --profile all up -d` | **~3.1 GB** | Full appliance running all 19 continuous containers simultaneously (scrapers + nuvio). |

> [!TIP]
> The setup scripts start the `all` profile when no profile is selected. You can set a lean default in `.env` using `COMPOSE_PROFILES=core`, or run directly with `./setup.sh start core` or `.\setup.ps1 -Start -Profile core`. The bootstrapper still creates the AIOStreams manifest if optional metadata services are unavailable; those providers are omitted until their profile is enabled.

### 2. Application Configuration Profiles

AIO Local bundles tailored setup profiles selectable via the portal (`:8088`) or `.env`:
- **AIOStreams Flagship (`all-local-selfhosted.json`)**: Default profile pre-configured with Tamtaro SEL expressions, Vidhin release regexes, SeaDex anime scoring, Comet, Zilean, Torrentio, SubSense subtitles, StremThru Store, and Anime Kitsu.
- **Usenet Only (`usenet-only.json`)**: Dedicated pipeline for users with an NNTP Usenet account and NZB indexer(s) with **NO Debrid subscription required**. Automatically routes through Prowlarr Newznab indexers, InfiniDysk on-demand WebDAV/HTTP streaming, AIOMetadata, SubSense, and TsukiHime anime. Selectable via the **Usenet Only** mode pill on the setup portal or `STREAMING_MODE=usenet`.
- **Tamtaro Anime Only (`tamtaro-anime-only.json`)**: Strips western TV rules to optimize strictly for anime releases, NekoBT, Tsukihime, AnimeTosho, SubsPlease, and dual-audio ranking.
- **AIOMetadata Catalogs (`with-anime`, `usenet-only`, vs. `without-anime`)**: Choose between full mainstream catalogs plus 20+ dedicated anime catalogs (MAL schedules, season rows, studio spotlights) or clean movie/TV catalogs without anime rows.

See the [Anime Ecosystem & Profile Guide](docs/ANIME-AND-PROFILES.md) and [Streaming Path Guide](docs/STREAMING-PATH.md) for full template definitions and architectural diagrams.
---



## 🏗️ What is Integrated



| Category | Bundled Services | Purpose |

| :--- | :--- | :--- |

| **Core Aggregator** | AIOStreams (`:3001`) | Super-addon aggregator, filtering engine, BuiltinProxy & Stremio manifest generator |

| **Management & Watchdog** | AIO Portal (`:8088`), Stack Watchdog | Central setup wizard, dual manifest exporter, automated backups, and live integration monitor |

| **Scrapers** | Comet (`:8000`) | Fast torrent & multi-source scrapers querying local Prowlarr and Zilean |

| **Indexers & Cache** | Zilean (`:8181`), Prowlarr (`:9696`), Search Broker (`:8091`), Byparr (`:8191`) | DMM hash cache (<100ms lookup), intelligent indexer caching/deduplication broker, auto-provisioned indexers, and Cloudflare bypass |

| **Metadata & Artwork** | AIOMetadata (`:4005`), Posters+ (`:9039`), Anime Kitsu (`:7005`) | Rich streaming-provider catalogs (Netflix, Disney+, Apple TV+, Max, Prime), rating badges, and local anime metadata |

| **Subtitles** | SubSense (`:3100`) | Multi-provider subtitle aggregator (OpenSubtitles, SubSource, SubDL, YIFY) with WARP routing |

| **Personal Library & Cloud** | StremThru Store (`:8080/stremio/store`) | Instant library search & direct Stremio catalog mounting for personal Real-Debrid / TorBox / Premiumize cloud files |

| **Stream Proxies** | StremThru (`:8080`), Universal BuiltinProxy | Debrid store caching, stream proxying, multi-IP ban shield, and non-debrid HTTP stream shielding |

| **Usenet Engine** | InfiniDysk (`:3005`) | High-throughput Usenet and WebDAV streaming engine |

| **Web Players & Sync** | Stremio Web (`:8082`), Nuvio Web (`:8085`), SlickSync (`:8086`) | Modern web players with AniSkip (auto/hotkey skip) & player shortcuts, Trakt sync hub, collections builder |

| **Databases** | Shared PostgreSQL 16, Shared Redis 7 | High-performance backends for Zilean, Comet, and AIOMetadata |



The 19-service count covers continuous application, database, and platform containers monitored on `stremio-net`.

One-shot initialization jobs (database bootstrap, configuration provisioner) run at first boot and exit gracefully.

Trakt, Simkl, AniList, Gemini, and the subtitle/debrid providers are adapters

configured through the bundled AIOStreams, AIOMetadata, SlickSync, and

SubSense services rather than additional containers.



---



## 🎬 How the Streaming Path Works (End-to-End Architecture)

Every media query and stream playback undergoes a coordinated journey across the internal `stremio-net` microservices network. Below is the end-to-end data and transport flow:

```text
  [Stremio Player / Web / Mobile]
               │
               ▼
  1. Browse: AIOMetadata (:4005) + Posters+ badges (Cinemeta / TMDB / TVDB / MAL)
               │
               ▼
  2. Select: AIOStreams (:3000 / :3001) Stream Resolution
       ├── Intelligent Query Broker (:8091) ──► Prowlarr ──► Byparr (Cloudflare bypass)
       ├── Primary Local Scrapers ────────────► Comet (:8000), Zilean DMM (:8181), StremThru Store (:8080)
       ├── Public & Community Databases ──────► Torrentio (~30ms cloud index), RemuxDB (MediaInfo audio/HDR)
       └── Native DHT & Multi-Tracker Indexing ► Bitsearch & SolidTorrents via Prowlarr
               │
               ▼
  3. Debrid Cache Probe & Filtering
       ├── Debrid API validation (RealDebrid, Premiumize, Torbox, StremThru Store)
       └── Tamtaro SEL Expressions, Vidhin Release Regexes, and SeaDex Anime Quality Ranking
               │
               ▼
  4. Stream Selection & Playback via BuiltinProxy:
     https://aio.yourdomain.com/playback/<token>/video.mkv
       │
       ├──► Multi-IP Ban Shield: Outbound connections originate from SERVER IP only
       │    (Real-Debrid & Premiumize see 1 IP even if multiple devices stream simultaneously)
       │
       ├──► Non-Debrid Host Shield ("none"): External HTTP/free streams proxied via server
       │
       └──► HTTP 206 Partial Content: Byte-range streaming for instant seeking & scrubbing
               │
               ▼
  5. In-Player Polish:
       ├── SubSense (:3100) ──► Subtitles (OpenSubtitles, SubDL, SubSource)
       └── Portal (:8088) ────► AniSkip intro/outro auto-skip + keyboard shortcut 's'
```

### Stage-by-Stage Breakdown

1. **Catalog & Metadata Discovery**:
   - The player requests catalogs from standalone **AIOMetadata** (`:4005`), pulling from Cinemeta, TMDB, TVDB, MAL/Jikan, and AniList.
   - **Posters+** overlays dynamic IMDb, Trakt, and MAL rating badges directly onto poster artwork.
   - Manifest partitioning ensures catalog feeds are served exclusively by AIOMetadata, preventing duplicate catalog rows in Stremio.

2. **Parallel Scraper Fan-Out & Request Coalescing**:
   - When a title is clicked, AIOStreams queries enabled scrapers in parallel.
   - The **Intelligent Search Broker** (`:8091`) coalesces identical in-flight indexer queries into one upstream call, caches results in memory for 60s (<20ms response), and bypasses Cloudflare challenges via Byparr (`:8191`).
   - Primary local scrapers (**Comet**, **Zilean DMM cache**, **Anime Kitsu**) return instant local results without external scraping delays.
   - Selectable public databases (**Torrentio** cloud index at ~30ms, **RemuxDB** MediaInfo specs) inject massive pre-indexed release coverage without local crawler overhead.

3. **Native DHT & Multi-Tracker Indexing (Prowlarr + Byparr)**:
   - Prowlarr natively probes Bitsearch, SolidTorrents, and top public trackers with automated Cloudflare bypass via Byparr.
   - DHT meta-search indexers feed Comet and Zilean instant cached torrent hashes directly into AIOStreams without the overhead of heavy standalone scrapers.

4. **Instant Debrid Cache Validation & SEL Scoring**:
   - Discovered infohashes are checked against the user's debrid provider API (Real-Debrid, Premiumize, Torbox, AllDebrid, Debrid-Link) or StremThru Store (`:8080`).
   - Streams are filtered, deduplicated, and ranked using **Tamtaro SEL expressions**, **Vidhin regexes**, and **SeaDex** community ranks. Optimal 4K Remuxes, Web-DLs, and dual-audio anime releases are sorted to the top.

5. **The Playback Transport & Multi-IP Ban Shield (Zero Concurrency Violations)**:
   - Streams are returned as proxied URLs: `https://aio.yourdomain.com/playback/<token>/video.mkv`.
   - When the user presses Play, the connection routes into AIOStreams' **BuiltinProxy**.
   - BuiltinProxy resolves the debrid download link using the **Docker host server's public IP address**.
   - **Crucial Protection**: Because `FORCE_PROXY_PROXIED_SERVICES` routes all video chunks through the server, Real-Debrid and Premiumize only ever observe **one single IP address** (the server's IP). Multiple household family members can stream simultaneously across cellular 5G, office, and home Wi-Fi networks with zero risk of account suspension.

6. **Non-Debrid & Free Stream Shielding (`"none"`)**:
   - Direct HTTP streams, free scrapers, IPTV, or Usenet route through `${BASE_URL}/api/v1/proxy/...`, masking the user's personal IP address and location from untrusted third-party hosts.

7. **HTTP 206 Partial Content & Byte-Range Streaming**:
   - BuiltinProxy fully supports HTTP range headers (`Range: bytes=start-end`, `Accept-Ranges: bytes`, `Content-Range`).
   - Allows instant seeking, scrubbing, audio/subtitle track selection, and resume without downloading the full video file.

8. **In-Player Enhancements (Subtitles & AniSkip)**:
   - **SubSense** (`:3100`) injects synchronized subtitles from OpenSubtitles and SubDL on-the-fly.
   - The bundled Stremio Web player (`:8082` / `:3001`) queries `/api/aniskip`, fetching millisecond-accurate intro/outro timestamps and displaying interactive skip badges (`[Skip Intro (s)]`). Pressing `s` jumps past intro songs and recaps immediately.

For full technical specifications, packet header details, and curl diagnostic commands, see the [End-to-End Streaming Path & Transport Architecture Guide](docs/STREAMING-PATH.md).

---

## 🚀 Advanced Capabilities & Security Protections

### 1. Multi-IP Ban Shield & Non-Debrid Proxying

Debrid providers (Real-Debrid, Premiumize) enforce strict single-IP concurrency rules. Streaming from multiple devices on separate networks (e.g. mobile 5G and home Wi-Fi) triggers immediate account suspensions.

- **Universal Server-Side Proxying**: With `FORCE_PROXY_PROXIED_SERVICES`, all debrid playback routes exclusively through your host server's public IP address.
- **Non-Debrid Shielding (`"none"`)**: HTTP streams from free scrapers, IPTV, or direct hosters are also proxied through `${BASE_URL}/api/v1/proxy/...`, shielding your client device IP from untrusted third-party hosts.

### 2. Dedicated Anime Ecosystem & AniSkip Integration

AIO Local includes an end-to-end anime pipeline tailored for anime enthusiasts:

- **Built-in AniSkip**: Detects opening/ending sequences and automatically advances playback, or presents a temporary skip badge (`[Skip Intro (s)]` / `[Skip Outro (s)]`).
- **Player Keyboard Shortcuts**:
  - `s` — Skip intro / outro
  - `Space` / `k` — Play / pause
  - `←` / `→` or `j` / `l` — Seek backward / forward 10 seconds
  - `f` — Toggle fullscreen
  - `m` — Toggle mute
- **Anime Kitsu Microservice (`:7005`)**: Local service that maps Kitsu anime IDs to IMDb/TheTVDB IDs, ensuring scrapers locate the correct torrent infohashes and debrid cache files for non-standard season arcs.
- **SeaDex Community Scoring**: AIOStreams automatically references the community SeaDex database (`config["enableSeadex"] = True`) to prioritize the best releases from top release groups (Beatrice-raws, Coalgirls, SubsPlease, Erai-raws).
- **20+ Anime Catalogs & Schedules**: Browse daily airing schedules, top upcoming, season rows, and animation studio spotlights (ufotable, MAPPA, KyoAni, Madhouse) with Posters+ rating badges.

See the [Anime Ecosystem & Profile Guide](docs/ANIME-AND-PROFILES.md) for full architecture details.

### 3. StremThru Store (Debrid Cloud Library in Stremio)

Mount your personal debrid cloud downloads (Real-Debrid, Premiumize, TorBox, AllDebrid, Debrid-Link) directly as browsable catalogs inside Stremio:
- Catalog prefix: `st:store:<service>:`
- Fast streaming of pre-downloaded torrents and personal media directly from your cloud library.

### 4. Intelligent Search Broker

A dedicated low-latency query broker (`:8091`) sits between scrapers and Prowlarr:
- **Deduplication & 60s Result Caching**: Cold queries resolve in ~3.4s; warm cache queries return in <20ms.
- **Automatic Dead-Indexer Bypassing**: Temporarily removes failing or rate-limited indexers from the query pool to prevent scraper timeouts.

### 5. Automated Stack Backups & Watchdog

- **Backup Scheduler**: Set `BACKUP_SCHEDULE=daily`, `weekly`, or `off` in `.env`. Automatically creates complete snapshots of SQLite databases, PostgreSQL clusters, and environment configurations.
- **Memory Watchdog**: Background watchdog monitors container memory limits and initiates graceful recycling if thresholds are approached.

---

## 🧪 Automated Testing & Verification



The project includes continuous integration unit tests, database provisioning tests, and live end-to-end integration probes:



```sh

# 1. Continuous Integration Regression Test Suite (Unit & database provisioning tests)

docker compose -p aio-tests -f compose.test.yml run --rm tests

docker compose -p aio-tests -f compose.test.yml run --rm browser-tests

docker compose -p aio-tests -f compose.test.yml run --rm database-test

docker compose -p aio-tests -f compose.test.yml down --volumes



# 2. Comprehensive End-to-End Suite (Live queries, cache, scraper, and playback through the full stack)

docker exec aio-portal python3 /app/tests/check_all_services_e2e.py



# 3. Remote Playback Probe (HTTP 206 Partial Content byte streaming via AIOStreams BuiltinProxy)

docker exec aio-portal python3 /app/tests/check_playback.py

```



---



## 🔑 Credentials and Upgrades



Keys remain in your local `.env`, service configuration, and Docker environment. The Setup Portal never prints stored secrets back to the browser; only a `SAVED` indicator is displayed.



- **Unique Secret Generation**: `setup.sh` automatically generates unique cryptographic keys for all internal services (`SECRET_KEY`, `POSTGRES_PASSWORD`, `PROWLARR_API_KEY`, etc.) when creating `.env`.

- **Do not commit `.env` or `data/`**: The `.dockerignore` and `.gitignore` exclude all local runtime storage and credentials.

- **Upgrades**:

  ```sh

  git pull --ff-only origin main

  docker compose pull --ignore-buildable

  docker compose up -d --build

  ```

  Then open the portal and choose **Connect my stack** to re-verify manifests and refresh services.



### Internet-facing deployment



The portal enables password-free access on local networks by default. If you expose port 8088 directly to the public internet without a reverse proxy, set `PORTAL_AUTH_REQUIRED=true` and configure `ADDON_PASSWORD` in `.env`. Authentication failures are rate-limited, state-changing requests reject foreign origins (CSRF protection), and portal responses disable caching and framing.

Expose only ports 3001 and 4005 through a TLS reverse proxy or Cloudflare Tunnel; keep port 8088 restricted to the administration network.



---



## 🧩 Standalone Custom Stack Builder (Offline Tool)



If you ever want to generate a custom, stripped-down Compose setup with selected microservices, use the standalone [Custom Stack Builder](tools/stack-builder):

* Open [`tools/stack-builder/index.html`](tools/stack-builder/index.html) directly in any browser.

* **100% client-side** and uncoupled from the rest of the running stack.

* Generates tailored `docker-compose.yml`, `.env`, and `01-init-dbs.sql` files for custom or manual deployments.


Current validation: 123 Python regression tests, twelve browser checks, image-only startup, portal apply, fixture upgrade/rollback and timed movie/episode routing tests. Earlier movie/episode decode evidence is in [release validation](docs/RELEASE-VALIDATION.md); current [routing validation](docs/ROUTING-VALIDATION.md) distinguishes media reads from decoding and public-address checks.


### Lowering Zilean background CPU usage

Zilean defaults to `ZILEAN_CPU_LIMIT=0.5`, a total allowance of half one logical
CPU (approximately 50% in Docker stats). It can run on any available CPU, but
Docker does not guarantee an even spread across cores. Background imports will
take longer. This limit applies to Zilean only; PostgreSQL has a separate budget.

Existing installations should set `ZILEAN_CPU_LIMIT=0.5` in `.env` or the Docker
management app's environment editor; an existing value overrides the new default.
For a source Compose installation, apply the change with:

```sh
docker compose --profile scrapers up -d --no-deps --force-recreate zilean
```

For a management-app installation, update the stack with the latest
`compose.manager.yml`, set the variable, and redeploy Zilean. A simple container
restart does not apply changed Compose limits. Check sustained usage with
`docker stats`; raising the limit to `1.0` allows roughly 100% if indexing is too slow.

### Startup checklist and playback testing

The portal shows a prominent startup checklist and keeps **Test my setup** locked
while setup runs, settings have unapplied changes, or readiness cannot be checked.
It checks enabled service connections, the configured streaming manifest, and the
search/Usenet endpoints used by the selected deployment. Services outside the
selected Compose profiles are shown as **Optional off** and do not block testing.
The server checks readiness again before accepting a full playback test.

If a service stays at **Waiting / unavailable**, open setup progress and logs;
check that the selected Compose profile is running, then retry configuration if
setup failed. The checklist refreshes automatically while the page is visible.
Readiness does not mean an initial Zilean data import has completed or that a title
has streams. The playback test separately verifies credentials, discovery and a
media read. Browser playback is reported only when the preview starts playing.

### Appliance setup and Docker networking

The `docker run` appliance starts a temporary status-only portal while its inner
Docker engine starts. The functional portal, controller and bootstrapper then run
on the same Compose network as AIOStreams. Wait for the startup page to reconnect
before entering keys. Setup applies saved settings to containers before provisioning
profiles and indexers; a failed AIOStreams readiness check stops provisioning.

Saved settings live in `/data/.env` with the rest of the appliance data. Reuse your
existing `/data` volume when replacing the image. For installations created before
this persistence fix, preserve `/app/.env` from the existing container before
replacing it; a data volume alone may not contain those older saved settings.
The appliance release check uses disposable data to exercise actual `docker run`
networking and controller provisioning before publishing the image. Paid-provider
authorization and real NNTP downloads still require testing on your installation.
