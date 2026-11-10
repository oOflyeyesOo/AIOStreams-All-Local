# Anime Ecosystem & Stack Profile Guide

This guide details the dedicated anime enhancements integrated across **AIO Local**, as well as the full breakdown of **Docker Compose resource profiles** and **AIOStreams / AIOMetadata configuration templates**.

---

## Part 1: Dedicated Anime Enhancements

AIO Local includes a comprehensive anime pipeline designed to solve common pain points with anime streaming: non-standard season/episode numbering, missing opening/ending skip times, unverified release quality, and fragmented catalog discovery.

```text
                               +-------------------------------------------------------------+
                               |                 Stremio Web Player (:8082 / :3001)          |
                               |  - On-screen [Skip Intro (s)] / [Skip Outro (s)] badges     |
                               |  - Player hotkeys: 's' (skip), Space/k, j/l, f, m           |
                               +------------------------------+------------------------------+
                                                              |
                                           +------------------+------------------+
                                           |                                     |
                                  AniSkip Timestamps                     Stream Resolution
                                  (:8088/api/aniskip)                    (:3000 / :3001)
                                           |                                     |
                                           v                                     v
                           +-------------------------------+     +-------------------------------+
                           |      Portal AniSkip Proxy     |     |     AIOStreams + SeaDex       |
                           |  - IMDb/TVDB -> MAL Mapping   |     |  - SeaDex Community Scoring   |
                           |  - AniSkip Interval DB        |     |  - Japanese / Romaji Parser   |
                           |  - Accurate OP/ED/Recap Times |     |  - Dual-Audio Prioritization  |
                           +-------------------------------+     +---------------+---------------+
                                                                                 |
                         +-------------------------------------------------------+-------------------------------------------------------+
                         |                                                       |                                                       |
                         v                                                       v                                                       v
         +-------------------------------+                       +-------------------------------+                       +-------------------------------+
         |     Anime Kitsu Microservice  |                       |   Dedicated Anime Scrapers    |                       |   AIOMetadata 20+ Catalogs    |
         |  - Port :7000 (Local Service) |                       |  - AnimeTosho (Priority 5)    |                       |  - MAL/Jikan Airing Schedules |
         |  - Kitsu ID -> IMDb Mapping   |                       |  - Nyaa (Priority 10)         |                       |  - Seasons (Winter/Spring...) |
         |  - Arc & Franchise Handling   |                       |  - SubsPlease / Erai-raws     |                       |  - Studio Catalogs (Mappa...) |
         +-------------------------------+                       |  - NekoBT & Tsukihime Presets |                       |  - Posters+ MAL Ratings       |
                                                                 +-------------------------------+                       +-------------------------------+
```

### 1. Built-in AniSkip Integration (Zero-Config Intro/Outro Skipping)
- **Automatic Interval Detection**: When an episode starts playing in Stremio Web (`:8082` / `:3001`), the embedded player queries the setup portal's backend (`/api/aniskip?id=...`).
- **Smart ID Translation**: The backend automatically maps IMDb or TVDB episode IDs to MyAnimeList (MAL) anime IDs via `resolve_mal_id()`, querying the community AniSkip database for verified timestamp boundaries.
- **On-Screen Skip Badges**: Displays clean, interactive badges (`[Skip Intro (s)]`, `[Skip Outro (s)]`, `[Skip Recap]`) that advance playback instantly past theme songs and recaps.
- **Keyboard Shortcut**: Press `s` at any time during an intro or outro to jump immediately to the episode content.

### 2. Anime Kitsu Local Microservice (`:7000`)
- **Franchise & Season Disambiguation**: Anime often structures sequels as separate titles rather than standard TV seasons (e.g. *Attack on Titan: The Final Season* vs. *Season 4*).
- **Local Resolution**: Running on `stremio-net` at port `7000`, the bundled `anime-kitsu` container translates Kitsu catalog queries to IMDb/TVDB IDs locally with zero external latency, ensuring scrapers locate the correct torrent infohashes and debrid cache files.

### 3. SeaDex Community Quality Scoring
- **Automated Best-Release Prioritization**: In `init/bootstrap/setup_stack.py`, `config["enableSeadex"] = True` is enabled out of the box.
- **Curated Release Groups**: AIOStreams cross-references the community SeaDex database to detect and prioritize the definitive release for any given anime title—favoring top-tier encoders (e.g. Beatrice-raws, Coalgirls, Commie, SubsPlease, Erai-raws) over re-encoded low-bitrate rips.
- **Dual-Audio & Subtitle Track Matching**: Tamtaro SEL expressions ensure multi-audio releases (Japanese original + English dub) and softsubs with ASS styling are ranked appropriately.

### 4. Dedicated Anime Scrapers & Prioritized Indexers
The stack provisions and prioritizes high-speed anime indexers in Prowlarr and AIOStreams:
- **AnimeTosho (Priority 5)**: Automated torrent and Usenet indexer for anime releases.
- **Nyaa (Priority 10)**: The world's largest public anime torrent index.
- **SubsPlease (Priority 15)** & **Mikan (Priority 15)**: Fast automated simulcast release feeds.
- **Shana Project, NekoBT, AniBT, and DMHY (Priority 15-20)**: Comprehensive raws and translated fansubs.
- **Native AIOStreams Presets**: Includes pre-configured `anime-tosho-new`, `neko-bt`, and `tsukihime` scrapers with custom regex parsers.

### 5. 20+ Anime Catalogs & Schedules (AIOMetadata)
The default `tamtaro-aiometadata-with-anime.json` configuration equips Stremio with an extensive anime library:
- **Daily Airing Schedules**: Direct Jikan/MAL feeds organizing currently airing anime by day of the week (Monday through Sunday).
- **Trending & Rankings**: Top Airing Anime, Top Upcoming, Top Anime TV Series, Top Anime Movies.
- **Seasonal Catalogs**: Filter anime by broadcast season (e.g. Fall 2026, Summer 2026).
- **Studio Catalogs**: Dedicated browsable rows for celebrated animation studios (ufotable, MAPPA, Kyoto Animation, Madhouse, Bones, Wit Studio, CloverWorks, A-1 Pictures, CoMix Wave).
- **Posters+ MAL Rating Badges**: Displays official MyAnimeList scores alongside IMDb ratings directly on catalog posters.
- **Watch Tracking**: Integrated synchronization for MyAnimeList (`malWatchTracking: True`) and AniList (`anilistWatchTracking: True`).

---

## Part 2: Stack Profiles (Resource & Docker Tuning)

AIO Local uses modular Docker Compose profiles to scale from low-memory single-board computers (Raspberry Pi 5, 2GB VPS) to enterprise media servers:

```bash
# Launch a specific profile
docker compose --profile <profile_name> up -d

# Or configure your default profile in .env:
COMPOSE_PROFILES=core
```

| Profile | RAM Usage | Included Services & Description |
| :--- | :--- | :--- |
| **`core`** | **~1.1 GB** | **Recommended Lean Setup**: Runs AIOStreams, Comet, AIOMetadata, Posters+, SubSense, Shared PostgreSQL 16, Shared Redis 7, and Setup Portal. Ideal for low-memory VPS or lightweight servers relying on Torrentio and Comet. |
| **`scrapers`** | **~3.5 GB** | **Full Local Crawlers**: Launches `core` plus MediaFusion, Sootio (Multi-Scraper), Zilean (Local DMM Hash Cache), Prowlarr (`:9696`), FlareSolverr (`:8191`) (`:8004`), and Anime Kitsu (`:7000`). |
| **`proxies`** | **~1.8 GB** | **Extended Proxy & Usenet Routing**: Launches `core` plus StremThru proxy router, and InfiniDysk Usenet Engine (`:3005`). |
| **`web`** | **~1.6 GB** | **Web Players & Sync Hub**: Launches `core` plus Stremio Web Player (`:8082`), Nuvio Web Player (`:8085`), and SlickSync Hub (`:8086`). |
| **`usenet`** | **~2.2 GB** | **Dedicated Usenet Streaming**: Launches `core` plus InfiniDysk (`:3005`), NZBDav, and Prowlarr configured with Newznab indexers for direct NNTP debrid-free streaming. |
| **`all`** (Default) | **~4.5 GB** | **Complete Appliance**: Runs all 22 microservices simultaneously on `stremio-net` with zero missing components. |

---

## Part 3: Configuration Templates & Presets

In addition to Docker runtime profiles, AIO Local includes pre-tuned JSON templates for **AIOStreams** and **AIOMetadata**:

### 1. AIOStreams Profiles (`templates/setup-templates/` & `templates/builtin/`)

| Template | File Name | Description |
| :--- | :--- | :--- |
| **All-Local Self-Hosted (Default)** | `all-local-selfhosted.json` | The flagship profile. Pre-configured with Tamtaro SEL expressions, Vidhin regexes, Seadex anime scoring, Comet, Zilean, Torrentio (public index), SubSense subtitles, StremThru Store, and Anime Kitsu. |
| **Usenet Only (NNTP & NZB)** | `usenet-only.json` | Streamlined pure Usenet configuration for users with an NNTP provider and NZB indexer without any debrid subscription. Routes through Prowlarr Newznab indexers, InfiniDysk on-demand WebDAV/HTTP streaming, AIOMetadata, SubSense subtitles, and TsukiHime anime. |
| **Tamtaro Complete Suite** | `tamtaro-complete.json` | Full Tamtaro sorting and filtering suite containing 100+ release groups, multilingual exclusions, and multi-indexer parsing. |
| **Tamtaro Anime Only** | `tamtaro-anime-only.json` | Dedicated anime-centric profile. Strips out mainstream western TV rules, optimizing specifically for anime releases, NekoBT, Tsukihime, AnimeTosho, SubsPlease, SeaDex quality ranks, and dual-audio preferences. |
| **Debrid Starter** | `debrid-starter.json` | Lightweight template intended for single-debrid setups without extended custom scrapers. |
| **Core Stable TorBox (4K / 1080p)** | `core-stable-torbox-4k.json` | Tailored profiles optimized for TorBox debrid caching and seedbox streaming limits. |

### 2. AIOMetadata Catalog Profiles (`templates/aiometadata-configs/`)

Selected directly in the Setup Portal (`:8088`):

| Template | File Name | Description |
| :--- | :--- | :--- |
| **Tamtaro with Anime (Default)** | `tamtaro-aiometadata-with-anime.json` | Full cinematic library with movies, TV series, streaming platform catalogs (Netflix, HBO, Disney+, Apple TV+), plus the **20+ dedicated Anime catalogs** (MAL schedules, seasons, studios) with Posters+ rating overlays. |
| **Usenet Only (NNTP InfiniDysk & Prowlarr)** | `usenet-only.json` | Optimized catalog layout tailored for Usenet-only streaming pipelines, pairing seamless movie/TV/anime discovery with zero debrid dependencies. |
| **Tamtaro without Anime** | `tamtaro-aiometadata-without-anime.json` | Clean mainstream setup containing all movie and TV catalogs, but omitting anime catalogs to keep Stremio's home screen focused exclusively on western media. |
| **Grabberhawk Config** | `grabberhawk-aiometadata-config.json` | Community catalog layout featuring alternative curation and list sorting. |

---

## Part 4: Switching Profiles & Templates

### Via Setup Portal (`http://localhost:8088`)
1. Open the portal at `http://localhost:8088` (or your public portal domain).
2. Expand the **AIOMetadata Template** dropdown to switch between `tamtaro-aiometadata-with-anime.json` and `tamtaro-aiometadata-without-anime.json`.
3. Expand **Public & Community Databases** to toggle Torrentio, DMM, and RemuxDB.
4. Click **Save Configuration & Connect** to hot-reload the configuration across all running containers.

### Via Command Line (`.env`)
To change your active templates or Docker profiles without using the UI:
```bash
# Set Docker Compose profile
COMPOSE_PROFILES=core

# Set AIOMetadata catalog template
AIOMETADATA_TEMPLATE=tamtaro-aiometadata-with-anime.json

# Toggle Anime and Public Databases
ENABLE_TORRENTIO=true
ENABLE_DMM=true
ENABLE_REMUXDB=true

# Restart containers to apply
docker compose up -d
```
