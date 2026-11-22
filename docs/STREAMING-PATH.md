# End-to-End Streaming Path & Transport Architecture

This document describes how media requests travel through the **AIO Local** stack—from catalog discovery to byte-range playback transport and multi-device debrid IP protection.

---

## 1. Architectural Topology Overview

All media requests flow through a unified Docker bridge network (`stremio-net`). Video streams and catalog metadata are partitioned to avoid bottlenecks and duplicate catalog registrations.

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
         |  - LumiereDB (:8000)          |                       |  - Torrentio (Public Index)   |                       |  - BuiltinProxy (:3000)       |
         |  - Zilean DMM Cache (:8181)   |                       |  - RemuxDB (MediaInfo/Codecs) |                       |  - Single-IP Debrid Bridge    |
         |  - Prowlarr & Byparr (:8191)  |                       |  - DMM Community Hashlists    |                       |  - Non-Debrid Host Shield     |
         |  - StremThru Store (:8080)    |                       +-------------------------------+                       |  - HTTP 206 Partial Content   |
         |  - SubSense Subtitles (:3100) |                                                                               +---------------+---------------+
         |  - Usenet (InfiniDysk :3005)  |                                                                                               |
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
1. **Catalog Query**: The client browses movies, series, or anime catalogs via the standalone **AIOMetadata** instance (`${AIOMETADATA_HOST}` or `http://aiometadata:4005`).
2. **Metadata Enrichment**: AIOMetadata aggregates Cinemeta, TMDB, TheTVDB, IMDb, and AniList/Jikan data.
3. **Poster Artwork & Ratings Badges**: Posters+ dynamically overlays IMDb, Trakt, and MAL ratings badges onto posters.
4. **Manifest Partitioning**: Catalog feeds are managed solely through AIOMetadata; stream resolution is delegated to AIOStreams.

---

### Stage 2: Stream Request Fan-Out & Aggregation
When a user selects a title, Stremio sends a stream resolution request to AIOStreams, which coordinates a parallel fan-out across configured scrapers:

1. **Prowlarr (`:9696`) & Byparr (`:8191`)**: Prowlarr is **100% dedicated to torrent indexing** (Torznab). Byparr handles Cloudflare-protected torrent indexers automatically. Usenet/Newznab indexers bypass Prowlarr entirely, eliminating serialized multi-tracker latency overhead and Cloudflare challenge timeouts.

2. **Primary Scrapers**:
   - **LumiereDB (`:8000`)**: Local SQLite search index for fast hash lookups.
   - **Zilean (`:8181`)**: Local SQLite database of cached Debrid Media Manager (DMM) torrent hashes. Resolves popular releases in <50ms.
   - **Torrentio Public Index**: When `ENABLE_TORRENTIO=true`, queries Torrentio's cloud index in ~30ms.
   - **StremThru Store (`:8080`)**: Queries the user's personal Real-Debrid / Torbox cloud for already-downloaded files.
   - **Direct Usenet & Newznab Indexers**: When Usenet is enabled, AIOStreams queries direct Newznab indexers (e.g. altHUB, DrunkenSlug, AnimeTosho) natively in parallel with sub-second resolution (~250ms latency), completely bypassing Prowlarr, while InfiniDysk handles on-demand NNTP downloads. Easynews direct search runs alongside if configured.

---

### Stage 3: Debrid Cache Probe, Filtering & URL Generation
1. **Instant Debrid Cache Validation**: Discovered infohashes are checked against the user's debrid provider API (Real-Debrid, Premiumize, TorBox, AllDebrid, Debrid-Link). Only pre-cached torrents are prioritized as instantly streamable.

2. **RemuxDB Codec Probing** (`ENABLE_REMUXDB=true`): AIOStreams queries RemuxDB for precise MediaInfo container specs (e.g. TrueHD 7.1 Atmos, Dolby Vision Profile 7/8).

3. **Tamtaro SEL & Vidhin Regex Scoring**: Streams are filtered, deduplicated, and ranked using Tamtaro SEL rules. Unwanted releases are purged; optimal 4K/1080p remuxes are sorted to the top.

4. **Stream URL Wrapping**: AIOStreams wraps each stream into a secured proxy URL:
   ```text
   http://aio.yourdomain.com/playback/<signed_token>/video.mkv
   ```

---

## 4. Stage 4: Playback Transport & Multi-IP Ban Shield

### The Multi-IP Concurrency Problem
Debrid services enforce strict anti-account-sharing rules: an account may only stream from **one public IP address** at a time. Concurrent streams from different IPs (e.g. home fiber + mobile 5G) can trigger account suspension.

### The AIO Local Solution: BuiltinProxy Shield
AIOStreams' native **BuiltinProxy** routes all upstream debrid traffic through the server's single public IP:
```bash
FORCE_PROXY_ENABLED=true
FORCE_PROXY_ID=builtin
FORCE_PROXY_URL=${BASE_URL}
FORCE_PROXY_PROXIED_SERVICES=["realdebrid","premiumize","alldebrid","torbox","debridlink","easynews","nzbdav","none"]
```

```text
 [Client A: Home Wi-Fi]       [Client B: Mobile 5G]       [Client C: Remote Friend]
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
                                        v
                        +-------------------------------+
                        |    Real-Debrid / Premiumize   |
                        |         CDN Edge Servers      |
                        |  (Sees ONLY 198.51.100.1)     |
                        |   => Zero Multi-IP Violations |
                        +-------------------------------+
```

---

### Usenet-Only (NNTP & NZB Indexer) Streaming

For users with **only a Usenet server** and **Newznab indexer(s)** without any debrid account:

1. Set `STREAMING_MODE=usenet` in `.env` (or select **Usenet Only** in the Setup Portal).
2. AIOStreams queries direct Newznab indexers (e.g. altHUB, DrunkenSlug, AnimeTosho) natively in parallel (~250ms latency), bypassing Prowlarr; debrid-dependent scrapers are automatically disabled, leaving Prowlarr 100% dedicated to torrent indexers.
3. When the user presses play, AIOStreams passes the chosen NZB to **InfiniDysk** (`http://infinidysk:3000`), which handles on-demand NNTP downloads and streams the video over HTTP/WebDAV with full byte-range seeking.
4. All playback proxies through BuiltinProxy at `${BASE_URL}/playback/...` — remote players never need direct access to InfiniDysk's internal port.

---

### HTTP 206 Partial Content & Byte-Range Streaming
BuiltinProxy fully proxies and preserves HTTP Range headers, enabling smooth scrubbing and instant resume without buffering the full file. Example response:
```http
HTTP/1.1 206 Partial Content
Content-Type: video/x-matroska
Accept-Ranges: bytes
Content-Range: bytes 1048576-2097151/524288000
```

---

### Usenet & Hybrid Failover Matrix

| Mode | Provider Setting | Preferred Source | Secondary Fallback | `allowCrossType` | Failover Outcome |
|---|---|---|---|---|---|
| **Usenet Only** | `STREAMING_MODE=usenet` | InfiniDysk NZBDAV (`:3005`) | Alternate NZB candidate | `False` | Fallback stays on Usenet |
| **Direct EasyNews** | `EASYNEWS_USER` + `PASS` | EasyNews Search | Alternate EasyNews match | `False` | Fallback to next match |
| **Hybrid Mode** | `STREAMING_MODE=hybrid` | Debrid Cached Release | InfiniDysk / EasyNews | `True` | Uncached debrid falls back to Usenet |

If a debrid link expires or a stream fails, `config["failover"]` activates automatically, attempting up to 3 alternate cached releases without terminating the player session.

---

## 5. Stage 5: In-Player Enhancements

### SubSense Subtitles (`:3100`)
SubSense queries OpenSubtitles, SubDL, and SubSource using server-side encrypted API keys. Matched `.srt` or `.vtt` subtitles are sanitized and injected directly into the player stream.

### Built-in AniSkip Proxy (`:8088/api/aniskip`)
The portal resolves IMDb/TVDB IDs to MAL IDs and queries the AniSkip API for opening/ending timestamps with millisecond precision. The player presents an on-screen skip badge and supports instant skipping via keyboard shortcut `s`.

---

## 6. Diagnostic Commands

```bash
# Verify AIOStreams BuiltinProxy status
curl -fsSL http://localhost:3001/api/v1/status

# Test HTTP 206 Partial Content byte streaming (first 1024 bytes)
curl -i -r 0-1023 "http://localhost:3001/playback/<token>/video.mkv"

# Verify AniSkip proxy resolution
curl -s "http://localhost:8088/api/aniskip?id=tt9335498&season=1&episode=1"
```
