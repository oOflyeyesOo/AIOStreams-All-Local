# End-to-End Streaming Path & Transport Architecture

This document provides a technical deep-dive into how media requests travel through the **AIO Local** stack—from initial catalog discovery and scrapers fan-out to byte-range playback transport and multi-device debrid IP protection.

---

## 1. Architectural Topology Overview

All media requests flow through a unified Docker bridge network (`stremio-net`). Video streams and catalog metadata are partitioned cleanly to avoid bottlenecks and duplicate catalog registrations.

```text
                               +-------------------------------------------------------------+
                               |                  Client Applications                        |
                               |  (Stremio Web, Stremio Desktop, Stremio Mobile, Android TV) |
                               +------------------------------+------------------------------+
                                                              |
                                           +------------------+------------------+
                                           |                                     |
                                  Catalog Requests                       Playback Stream Requests
                                  (meta.yourdomain.com:4005)             (aio.yourdomain.com:3001)
                                           |                                     |
                                           v                                     v
                           +-------------------------------+     +-------------------------------+
                           |      AIOMetadata (:4005)      |     |      AIOStreams (:3000)       |
                           |  - Cinemeta, TVDB, IMDb, MAL  |     |  - Tamtaro SEL Ranking        |
                           |  - Posters+ Ratings Badges    |     |  - Stream Deduplication       |
                           |  - AniList / Kitsu Catalogs   |     |  - BuiltinProxy Transport     |
                           +-------------------------------+     +---------------+---------------+
                                                                                 |
                         +-------------------------------------------------------+-------------------------------------------------------+
                         |                                                       |                                                       |
                         v                                                       v                                                       v
         +-------------------------------+                       +-------------------------------+                       +-------------------------------+
         |    Primary Local Scrapers     |                       |  Public / Community Databases |                       |     Transport & IP Shield     |
         |  - Comet (:8000)              |                       |  - Torrentio (Public Index)   |                       |  - BuiltinProxy (:3000)       |
         |  - Zilean DMM Cache (:8181)   |                       |  - RemuxDB (MediaInfo/Codecs) |                       |  - Single-IP Debrid Bridge    |
         |  - Search Broker (:8091)      |                       |  - DMM Community Hashlists    |                       |  - Non-Debrid Host Shield     |
         |  - Prowlarr & Byparr (:8191)  |                       +-------------------------------+                       |  - HTTP 206 Partial Content   |
         |  - StremThru Store (:8080)    |                                                                               +---------------+---------------+
         |  - SubSense Subtitles (:3100) |                                                                                               |
         |  - Usenet (InfiniDysk :3005)  |                                                                                               v
         +-------------------------------+                                                                               +-------------------------------+
                                                                                                                         |     Upstream Providers        |
                                                                                                                         |  - Real-Debrid / Premiumize   |
                                                                                                                         |  - TorBox / AllDebrid CDN     |
                                                                                                                         |  - Usenet NNTP Servers        |
                                                                                                                         +-------------------------------+
```

---

## 2. Stage-by-Stage Request Journey

### Stage 1: Discovery & Catalog Browsing
1. **Catalog Query**: The client browses movies, series, or anime catalogs. The request targets the standalone **AIOMetadata** instance (`${AIOMETADATA_HOST}` or `http://aiometadata:4005`).
2. **Metadata Enrichment**: AIOMetadata aggregates Cinemeta, TheMovieDB (TMDB), TheTVDB, IMDb, MyAnimeList (MAL/Jikan), and AniList data.
3. **Poster Artwork & Ratings Badges**: Posters+ dynamically overlays IMDb, Trakt, and MAL ratings badges onto posters via `/poster?stremio_id=...`.
4. **Manifest Partitioning**: To eliminate duplicate catalog rows inside Stremio, catalog feeds are managed solely through AIOMetadata, while stream resolution is delegated to AIOStreams.

---

### Stage 2: Stream Request Fan-Out & Aggregation
When a user selects a title or episode, Stremio sends a stream resolution request:
```http
GET /stremio/{uuid}/{encryptedPassword}/stream/{type}/{id}.json HTTP/1.1
Host: aio.yourdomain.com
```

AIOStreams coordinates a parallel query fan-out across configured scrapers:

1. **Intelligent Query Broker (`:8091`) & Prowlarr (`:9696`)**:
   - Scrapers requiring Torznab/Newznab indexers route queries through the query broker.
   - The broker performs **request coalescing** (identical in-flight searches share a single upstream query), caches warm results in memory for 60 seconds (<20ms response), and bypasses Cloudflare challenges via Byparr (`:8191`).
   - If an indexer fails repeatedly, the broker applies an automated cooldown to protect search latencies.

2. **Primary Scrapers**:
   - **Comet (`:8000`)**: High-performance torrent crawler querying Prowlarr and Zilean.
   - **Zilean (`:8181`)**: Local SQLite database storing cached Debrid Media Manager (DMM) torrent hashes. Resolves popular releases in <50ms without external tracker requests.
   - **Torrentio Public Index**: When `ENABLE_TORRENTIO=true`, queries Torrentio's cloud index (`https://torrentio.strem.fun` or `TORRENTIO_URL`) in ~30ms to access millions of pre-indexed torrent releases without local crawler overhead.
   - **StremThru Store (`:8080`)**: Queries the user's personal Real-Debrid / Torbox cloud for files already downloaded to their account.
   - **Usenet Search (Built-in & Prowlarr)**: When enabled, searches configured Newznab indexers and Easynews search.

3. **Native DHT & Meta-Search Indexing (Prowlarr + Byparr)**:
   - Prowlarr auto-provisions DHT indexers (`Bitsearch`, `SolidTorrents`) and torrent feeds protected by Byparr.
   - Comet and Zilean consume these streams directly with sub-100ms hash probing, eliminating redundant external multi-scrapers.

---

### Stage 3: Debrid Cache Probe, Filtering & URL Generation
1. **Instant Debrid Cache Validation**:
   - Discovered infohashes are checked against the user's debrid provider API (Real-Debrid, Premiumize, TorBox, AllDebrid, Debrid-Link) or StremThru Store (`:8080`).
   - Only torrents pre-cached on debrid servers are prioritized as instantly streamable.

2. **RemuxDB Codec Probing (`ENABLE_REMUXDB=true`)**:
   - AIOStreams queries RemuxDB to obtain precise MediaInfo container specs (e.g. TrueHD 7.1 Atmos vs. DTS-HD MA, Dolby Vision Profile 7/8 vs. HDR10+).

3. **Tamtaro SEL & Vidhin Regex Scoring**:
   - Streams are filtered, deduplicated, and ranked using community Tamtaro Stream Expression Language (SEL) rules and Vidhin release regexes.
   - Unwanted releases (e.g. CAM, TeleSync, low-bitrate rips) are purged; optimal 4K/1080p remuxes and Web-DLs are sorted to the top.

4. **Stream URL Wrapping**:
   - Instead of returning direct provider CDN links or raw P2P infohashes to the client, AIOStreams wraps each stream into a secured proxy URL:
   ```text
   http://aio.yourdomain.com/playback/<signed_token>/video.mkv
   ```

---

## 4. Stage 4: Playback Transport & Multi-IP Ban Shield (Deep Dive)

The playback transport layer is the core security boundary of AIO Local.

### The Multi-IP Concurrency Problem
Debrid services (Real-Debrid, Premiumize) enforce strict anti-account-sharing rules:
> **Real-Debrid Rule**: An account may only download or stream from **one public IPv4/IPv6 address** at any given moment. If connections originate from two different public IPs simultaneously (e.g. a family member on mobile 5G while another watches on home fiber), the account is immediately suspended or banned.

### The AIO Local Solution: BuiltinProxy Shield
AIO Local neutralizes this risk through AIOStreams' native **BuiltinProxy** configured with:
```bash
FORCE_PROXY_ENABLED=true
FORCE_PROXY_ID=builtin
FORCE_PROXY_URL=${BASE_URL}
FORCE_PROXY_PROXIED_SERVICES=["realdebrid","premiumize","alldebrid","torbox","debridlink","easynews","nzbdav","none"]
```

---

### Usenet-Only (NNTP & NZB Indexer) Streaming Journey (No Debrid Required)

For users who operate with **only a Usenet server (NNTP)** and **Newznab indexer(s)** without any Debrid account:

1. **Dedicated Usenet Mode**:
   - In the Setup Portal (`:8088`), select the **Usenet Only (NNTP & NZB Indexers — No Debrid)** provider pill (or set `STREAMING_MODE=usenet` in `.env`).
   - The setup portal exposes the NNTP server settings (Host, Port, User, Pass, TLS, Connections) and NZB indexer base address and API key as the primary setup fields, hiding debrid inputs.
   - The aggregator profile automatically loads `templates/builtin/usenet-only.json` (or `usenet-only.json`).

2. **Index Searching via Prowlarr**:
   - When a video title or episode is selected in Stremio, AIOStreams queries **Prowlarr** (`http://prowlarr:9696`) for Newznab NZB releases using the `prowlarr-usenet` preset.
   - For anime requests, **TsukiHime** directly queries anime NZBs and connects with InfiniDysk (`nzbdav`).
   - Debrid-dependent scrapers (Comet, Torrentio, StremThru Store) are automatically omitted or disabled so no wasted queries or timeout delays occur.

3. **On-Demand NNTP Downloading & WebDAV Serving via InfiniDysk**:
   - When the user presses play, AIOStreams passes the chosen NZB to **InfiniDysk** (`http://infinidysk:3000`).
   - InfiniDysk connects directly to the Usenet provider via multi-threaded NNTP article fetching, reconstructs the media stream on-the-fly, and serves the video over HTTP/WebDAV.

4. **Universal BuiltinProxy Streaming**:
   - Because `"nzbdav"` is registered in `config["proxy"]["proxiedServices"]`, playback URLs are transformed into `${BASE_URL}/playback/<session_token>/...` on the public AIOStreams port (`3001`).
   - Remote players (Stremio Web, Android TV, Mobile) never need direct network access to InfiniDysk's internal port (`3005`); all bytes stream cleanly through AIOStreams with full **HTTP 206 Partial Content (byte-range seeking)** support.

5. **Full Metadata & Subtitles**:
   - **AIOMetadata** provides the full cinematic catalog experience (Cinemeta, TMDB, TVDB, IMDb, Anime) with Posters+ rating badges.
   - **SubSense** automatically fetches subtitles from OpenSubtitles, SubDL, and SubSource.
   - **AniSkip** provides instant OP/ED skipping.

```text
 [Client A: Home Wi-Fi]       [Client B: Mobile 5G]       [Client C: Remote Friend]
   (IP: 198.51.100.14)          (IP: 203.0.113.88)           (IP: 192.0.2.77)
            |                            |                            |
            +----------------------------+----------------------------+
                                         |
                                         | All clients stream via:
                                         | https://aio.yourdomain.com/playback/...
                                         v
                         +-------------------------------+
                         |    AIOStreams BuiltinProxy    |
                         |   (Your Server / VPS Host)    |
                         |    Outbound IP: 198.51.100.1  |
                         +---------------+---------------+
                                         |
                                         | Upstream connections originate
                                         | exclusively from 198.51.100.1
                                         v
                         +-------------------------------+
                         |    Real-Debrid / Premiumize   |
                         |         CDN Edge Servers      |
                         |  (Sees ONLY 198.51.100.1)     |
                         |   => Zero Multi-IP Violations |
                         +-------------------------------+
```

#### Step-by-Step Playback Execution:
1. **Client Request**: The video player sends an HTTP `GET` request to `https://aio.yourdomain.com/playback/<token>/video.mkv`.
2. **Token Verification**: BuiltinProxy validates the encrypted session token containing provider credentials, file path, and stream metadata.
3. **Upstream Unrestriction**: BuiltinProxy communicates with the debrid provider API (e.g. `POST /unrestrict/link`) using the **Docker host server's public IP address**.
4. **Data Piping**: BuiltinProxy initiates an upstream stream to the debrid CDN and pipes chunks down to the player.
5. **Single-IP Isolation**: The debrid provider's firewall observes only **one** IP address (the Docker host server), regardless of how many devices are streaming concurrently across disparate cellular or home networks.

---

### Non-Debrid & Free Stream Shielding (`"none"`)
For streams that do not originate from a debrid provider (e.g. direct HTTP web links, IPTV feeds, free hosters, or Usenet):
- `FORCE_PROXY_PROXIED_SERVICES` includes `"none"`.
- Requests route through `${BASE_URL}/api/v1/proxy/...`.
- Untrusted third-party hosts never receive or log the end-user's home IP address, browser user-agent, or geolocation.

---

### HTTP 206 Partial Content & Byte-Range Streaming
Modern video players require byte-range seeking to support instant scrubbing, audio/video track switching, and subtitle synchronization.

BuiltinProxy fully proxies and preserves HTTP Range headers:
- **Client Header**: `Range: bytes=1048576-`
- **Server Response**:
  ```http
  HTTP/1.1 206 Partial Content
  Content-Type: video/x-matroska
  Accept-Ranges: bytes
  Content-Range: bytes 1048576-2097151/524288000
  Content-Length: 1048576
  ```
- This enables smooth scrubbing and instant resume without forcing the server or client to buffer the full media file.

---

### Automatic Failover & Self-Healing
If a debrid link expires, an upstream CDN node drops connection, or a stream fails:
- `config["failover"]` activates automatically.
- AIOStreams attempts up to 3 alternate cached releases (`maxAttempts: 3`), seamlessly failing over between debrid and Usenet (`allowCrossType: True`) without terminating the player session.

---

## 5. Stage 5: In-Player Enhancements

### 1. SubSense Subtitles (`:3100`)
- Stremio requests subtitles via SubSense (`http://subsense:3100/{encrypted_config}/manifest.json`).
- SubSense queries OpenSubtitles, SubDL, and SubSource using server-side encrypted API keys.
- Matched `.srt` or `.vtt` subtitles are downloaded, sanitized, and injected directly into the player stream.

### 2. Built-in AniSkip Proxy (`:8088/api/aniskip`)
- When streaming anime via the bundled Stremio Web player (`:3001`), the player queries the setup portal's `/api/aniskip` endpoint.
- The portal resolves IMDb / TVDB IDs to MyAnimeList (MAL) IDs and queries the AniSkip API.
- Opening (`op`), ending (`ed`), and recap intervals are returned with millisecond precision:
  ```json
  {
    "found": true,
    "malId": 38000,
    "results": [
      {"skipType": "op", "interval": {"startTime": 65.5, "endTime": 155.0}},
      {"skipType": "ed", "interval": {"startTime": 1320.0, "endTime": 1410.0}}
    ]
  }
  ```
- The player automatically presents an on-screen skip badge and supports instant skipping via keyboard shortcut `s`.

---

## 6. Diagnostic Probing & Verification Commands

To verify that the streaming path, range requests, and proxying are functioning correctly:

```bash
# 1. Verify AIOStreams BuiltinProxy status
curl -fsSL http://localhost:3001/api/v1/status

# 2. Test HTTP 206 Partial Content byte streaming (first 1024 bytes)
curl -i -r 0-1023 "http://localhost:3001/playback/<token>/video.mkv"

# 3. Verify AniSkip proxy resolution
curl -s "http://localhost:8088/api/aniskip?id=tt9335498&season=1&episode=1"

# 4. Verify Search Broker latency and caching
curl -s -w "\nTime: %{time_total}s\n" "http://localhost:8091/api/v1/search?query=Inception"
```
