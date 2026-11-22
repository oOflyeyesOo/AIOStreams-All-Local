# Anime Ecosystem & Stack Profile Guide

This guide covers the dedicated anime enhancements in **AIO Local** and the Docker Compose resource profiles and configuration templates.

---

## Part 1: Dedicated Anime Enhancements

AIO Local includes a comprehensive anime pipeline for non-standard season/episode numbering, opening/ending skip times, release quality scoring, and catalog discovery.

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
When an episode starts playing, the embedded player queries `/api/aniskip`. The backend maps IMDb/TVDB IDs to MAL IDs and queries the AniSkip database for verified timestamp boundaries. On-screen skip badges (`[Skip Intro (s)]`, `[Skip Outro (s)]`) advance playback instantly past theme songs. Press `s` to skip at any time.

### 2. Anime Kitsu Local Microservice (`:7000`)
Translates Kitsu catalog queries to IMDb/TVDB IDs locally (zero external latency), ensuring scrapers locate correct torrent infohashes and debrid cache files for franchise sequels with non-standard season numbering.

### 3. SeaDex Community Quality Scoring
`config["enableSeadex"] = True` is enabled by default. AIOStreams cross-references SeaDex to prioritize the definitive release for any anime title, favoring top-tier encoders (Beatrice-raws, SubsPlease, Erai-raws). Tamtaro SEL expressions rank dual-audio and ASS-subtitle releases appropriately.

### 4. Dedicated Anime Scrapers & Prioritized Indexers
- **AnimeTosho (Priority 5)**: DDL + Torrents + Usenet NZBs for anime.
- **Nyaa (Priority 10)**: The world's largest public anime torrent index.
- **SubsPlease (Priority 15)** & **Mikan (Priority 15)**: Fast automated simulcast feeds.
- **NekoBT, AniBT, DMHY (Priority 15–20)**: Fansubs and raws.
- Native presets: `anime-tosho-new`, `neko-bt`, `tsukihime` with custom regex parsers.

Optional anime scrapers (`ENABLE_ANIME_SOURCES=true`) add +18–35 net-new playable releases for niche fansubs but increase p95 search latency from ~0.15s to ~0.72s.

### 5. 20+ Anime Catalogs & Schedules (AIOMetadata)
The default `tamtaro-aiometadata-with-anime.json` configuration provides:
- **Daily Airing Schedules**: Jikan/MAL feeds organized by day of the week.
- **Trending & Rankings**: Top Airing, Top Upcoming, Top TV Series, Top Movies.
- **Seasonal Catalogs**: Filter by broadcast season (e.g. Fall 2026).
- **Studio Catalogs**: ufotable, MAPPA, Kyoto Animation, Madhouse, Bones, Wit Studio, and more.
- **Posters+ MAL Rating Badges**: MAL scores alongside IMDb ratings on posters.
- **Watch Tracking**: MyAnimeList (`malWatchTracking: True`) and AniList (`anilistWatchTracking: True`).

> [!NOTE]
> Jikan (MAL API) is pre-configured to use the free Tenrai public endpoint (`https://api.tenrai.org/v4`) by default. You can override it with `JIKAN_API_BASE` in `.env` if you prefer a self-hosted instance.

---

## Part 2: Stack Profiles (Docker Compose)

AIO Local uses modular Docker Compose profiles to scale from low-memory single-board computers to full media servers:

```bash
# Launch a specific profile
docker compose --profile <profile_name> up -d

# Or configure your default profile in .env:
COMPOSE_PROFILES=core
```

| Profile | RAM Usage | Included Services |
| :--- | :--- | :--- |
| **`core`** | **~1.1 GB** | AIOStreams, LumiereDB, AIOMetadata, Posters+, SubSense, Shared PostgreSQL 16, Shared Redis 7, Setup Portal. Ideal for low-memory VPS. |
| **`scrapers`** (Default Complete) | **~2.8 GB** | Everything in core plus all scrapers, indexers, proxies, Usenet, and Anime Kitsu. |
| **`nuvio`** | **~250 MB** | Nuvio Web Player (`:8085`) with AniSkip and admin dashboard. Combine with: `COMPOSE_PROFILES=scrapers,nuvio`. |
| **`all`** | **~3.1 GB** | All services simultaneously on `stremio-net`. |

> [!NOTE] LumiereDB is on the **`core`** profile and starts with AIOMetadata automatically.

---

## Part 3: Configuration Templates & Presets

### 1. AIOStreams Profiles (`templates/setup-templates/` & `templates/builtin/`)

| Template | File Name | Description |
| :--- | :--- | :--- |
| **All-Local Self-Hosted (Default)** | `all-local-selfhosted.json` | Pre-configured with Tamtaro SEL, Vidhin regexes, SeaDex anime scoring, Zilean, Torrentio, SubSense, StremThru Store, and Anime Kitsu. |
| **Usenet Only (NNTP & NZB)** | `usenet-only.json` | Pure Usenet configuration routing through direct Newznab presets in AIOStreams (~250ms latency, bypassing Prowlarr), native AIOStreams NNTP streaming engine, AIOMetadata, SubSense, and TsukiHime anime. |
| **Tamtaro Complete Suite** | `tamtaro-complete.json` | Full sorting and filtering suite with 100+ release groups, multilingual exclusions, and multi-indexer parsing. |
| **Tamtaro Anime Only** | `tamtaro-anime-only.json` | Dedicated anime profile optimizing for NekoBT, Tsukihime, AnimeTosho, SubsPlease, SeaDex, and dual-audio. |
| **Debrid Starter** | `debrid-starter.json` | Lightweight template for single-debrid setups without extended custom scrapers. |
| **Core Stable TorBox (4K / 1080p)** | `core-stable-torbox-4k.json` | Tailored for TorBox debrid caching and seedbox streaming limits. |

### 2. AIOMetadata Catalog Profiles (`templates/aiometadata-configs/`)

| Template | File Name | Description |
| :--- | :--- | :--- |
| **Tamtaro with Anime (Default)** | `tamtaro-aiometadata-with-anime.json` | Full library with movies, TV, streaming platform catalogs, plus 20+ anime catalogs with Posters+ rating overlays. |
| **Usenet Only** | `usenet-only.json` | Catalog layout for Usenet-only pipelines with zero debrid dependencies. |
| **Tamtaro without Anime** | `tamtaro-aiometadata-without-anime.json` | Movies and TV only — omits anime catalogs for a western-media-focused home screen. |
| **Grabberhawk Config** | `grabberhawk-aiometadata-config.json` | Community catalog layout with alternative curation and list sorting. |

---

## Part 4: Switching Profiles & Templates

### Via Setup Portal (`http://localhost:8088`)
1. Open the portal at `http://localhost:8088`.
2. Expand the **AIOMetadata Template** dropdown to switch between catalog profiles.
3. Toggle **Public & Community Databases** (Torrentio, DMM, RemuxDB) as needed.
4. Click **Save Configuration & Connect** to hot-reload across all running containers.

### Via Command Line (`.env`)
```bash
COMPOSE_PROFILES=core
AIOMETADATA_TEMPLATE=tamtaro-aiometadata-with-anime.json
ENABLE_TORRENTIO=true
ENABLE_DMM=true
ENABLE_REMUXDB=true
docker compose up -d
```
