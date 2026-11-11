# Optional sources and Usenet validation — 2026-11-07

## Torrentio, RemuxDB, and DMM Public Databases

To maximize stream resolution and release quality without imposing 24/7 background crawling burdens on local hardware, AIO Local bundles selectable upstream and curated public database integrations directly into AIOStreams and Zilean:

1. **Torrentio (`ENABLE_TORRENTIO=true`)**:
   - Queries the official Torrentio public index database (`https://torrentio.strem.fun`) directly.
   - Because Torrentio maintains a massive pre-crawled database of millions of indexed torrents, queries return in **~0.029 seconds** with zero local CPU, crawling, or storage overhead.
   - All stream requests are routed through AIOStreams' `BuiltinProxy`, ensuring 100% server-side IP isolation and preventing multi-IP debrid account bans (detailed in the [Streaming Path Architecture](STREAMING-PATH.md) guide).
   - Set `ENABLE_TORRENTIO=false` to omit Torrentio and rely exclusively on local scrapers. Configure `TORRENTIO_URL` to override with a custom endpoint.

2. **RemuxDB (`ENABLE_REMUXDB=true`)**:
   - Directly sources technical MediaInfo container probes from the public RemuxDB database.
   - Backfills exact audio codecs (e.g. TrueHD with Dolby Atmos, DTS-HD MA), video profiles, and HDR10+/Dolby Vision formats for accurate filtering and scoring.

3. **DMM Database (`ENABLE_DMM=true`)**:
   - Syncs curated community Debrid Media Manager (DMM) hashlists into our local **Zilean** container (`:8181`).
   - Enables sub-50ms instant cache hits for high-demand movie and TV releases directly from your private PostgreSQL database.

### Benchmark & Discovery Measurements

Read-only comparisons used the retained installation without changing its files
or profile. External discovery requests contained no provider credentials.
Premiumize cache checks went only to its official API; Comet used its existing
local configuration. Only counts and timings were retained.

| Title | Torrentio hashes | Absent from Comet | Also marked cached by Premiumize | Observed direct response |
|---|---:|---:|---:|---:|
| Dune: Part Two | 169 | 106 | 92 | 0.029 s |
| Game of Thrones S2E2 | 85 | 85 | 76 | 0.029 s |
| Inception | 99 | 80 | 60 | 0.026 s |
| Breaking Bad S1E1 | 76 | 75 | 68 | 0.030 s |

The fourth column counts hashes both absent from Comet and marked cached. These
are a four-title snapshot, not a universal coverage claim. Shared upstream caches
were not flushed; the response times are not cold-search measurements. Hash
availability does not prove the correct episode/file, language, entitlement or
successful decoding.

Keep one native Torrentio preset in AIOStreams. `providers: []` uses the adapter's
default source selection. Returned results included sources such as ThePirateBay,
1337x, Rutracker, Rutor, TorrentGalaxy, MagnetDL and RARBG; these labels describe
Torrentio results, not newly deployed local scrapers. Some overlap with Prowlarr
indexers is expected. Torrentio stays dedicated to AIOStreams native integration.
Do not add a second copy through Comet or another aggregator. Hash deduplication
removes duplicate results; global external-site request deduplication is not
established.

`ENABLE_TORRENTIO=false` disables the native preset. The legacy
`ENABLE_KNIGHTCRAWLER` switch remains a fallback if the canonical setting is
absent. A custom `KNIGHTCRAWLER_URL` replaces the endpoint; it never creates a
second preset. Usenet-only configurations omit it entirely.

The production native Torrentio adapter places enabled provider credentials in its configured addon URL and sends it to the selected external addon. This differs from the credential-free discovery benchmark above. Disable it with `ENABLE_TORRENTIO=false` if that sharing is unsuitable. Personalized manifests/profile exports are private configuration, not release files.

An isolated, credential-free native AIOStreams profile also passed movie/episode
discovery: 168/79 P2P candidates in 1.798/0.786 seconds. The native schema retained
cache-and-play, remux database, language inference, episode matching and sequential
failover settings. Paid playback was not exercised by this comparison.

Title/year matching requires TMDB. Bootstrap disables dependent features without a TMDB key.
Next-episode prefetch is opt-in (`AIO_PRECACHE_NEXT_EPISODE=true`), and failover
uses one attempt at a time to avoid hidden parallel provider calls.

## Local Indexing Architecture (Streamlined from External Scrapers)

Earlier appliance versions evaluated external scrapers (MediaFusion and Sootio).
Benchmarking revealed high latency costs, scrapers timing out on cold searches,
and redundant scraper overhead.

The stack has been streamlined to a high-speed local indexing and caching architecture:
- **Comet** queries local **Prowlarr** indexers and the **Zilean** DMM cache.
- **Search Broker** coalesces duplicate indexer searches and provides 60s in-memory caching.
- External multi-crawlers were retired in favor of native **Torrentio**, **RemuxDB**, and curated **DMM** hashlists.

## Usenet setup

The single-page form accepts server, port, username, password, TLS and connection
count, plus an optional Newznab URL/API key. Connect my stack supplies the current
InfiniDysk headless JSON schema and creates one native AIOStreams
`Prowlarr → InfiniDysk` Usenet route. Comet's installed indexer manager filters
Prowlarr indexers to `protocol == torrent`; the native Usenet route selects only
Usenet sources. This does not create a second torrent-search route.

Credentials are stored in the private local environment file. Base64 encoding
protects Compose syntax; it is not encryption. Passwords and configured manifest
URLs are not returned by the portal settings API. Protect the installation and
backup files. Enabling the form makes it authoritative over InfiniDysk's provider
list; unmanaged installations retain their existing JSON/UI configuration.

The real packaged controller, InfiniDysk and Prowlarr passed a local NNTP/Newznab
fixture test:

- Passwords containing dollar signs, quotes and `#` survived both Compose passes;
  InfiniDysk authenticated against the fixture (three successes, zero rejections).
- Reapplying without retyping the password preserved it and created no duplicate
  Newznab indexer. Managed address changes update the existing indexer in place.
- Optional Usenet route switched on, reached healthy state, and switched off again.
- Disabling Usenet emptied the effective provider list, disabled the managed NZB
  indexer, omitted its native route and retained the saved credentials.
- Default enabled-service checks passed 21/21. This includes TCP-only probes.

This verifies configuration, authentication and indexer provisioning. It does not
verify paid NNTP, TLS against a real provider, article retrieval, repair,
decompression or Usenet media decoding. Those remain acceptance gates.

## Retired External Scrapers

Slow external multi-scrapers (such as Sootio) were retired in favor of the Intelligent
Search Broker and native public databases. Rather than sequentially querying slow public
crawlers, search requests leverage local Prowlarr indexers protected by Byparr Cloudflare
challenge solving and instant DMM hash cache lookups.

## Fresh-run routing fixture isolation

The first Linux run of source `494102c` passed zero-restart startup, 21 endpoints,
and all optional-service/NNTP checks, then failed a repeated episode response in
the routing fixture. The exact immutable AIOStreams image passed that same test
locally; the failure was intermittent, not reproduced as a service restart.

Real IMDb episode IDs made the supposedly deterministic fixture invoke external
metadata work. The routing gate now uses synthetic episode IDs, explicitly turns
off metadata-dependent/background features, and retains all warm/concurrent
response and exact upstream call-count assertions. Failures report only counts,
timings and error categories. This isolates routing; it does not establish the
cause of the earlier intermittent failure or certify external metadata uptime.
Real-title Torrentio discovery and official provider cache checks remain separate
from this fixture and from unverified paid decoding.

## Incoming anime and EasyNews additions

Commit `cff5b30` arrived during acceptance. Its native addons are retained with
routing safeguards: Anime Tosho, nekoBT and TsukiHime are opt-in through the setup
page (`ENABLE_ANIME_SOURCES=true`), anime-only, single-instance, and limited to
compatible configured services. Without a compatible account they stay disabled.
TsukiHime may use the configured NNTP route; the other two require torrent/debrid
services. Extra AnimeTosho/SubsPlease definitions are not seeded again in Prowlarr.
Existing Prowlarr user configurations are preserved.

EasyNews uses one native `easynews-search` preset, restricted to the EasyNews
account itself. An EasyNews-only account
does not enable unsupported Comet/Torrentio routes. Configure `EASYNEWS_USER`
and `EASYNEWS_PASSWORD` in the private environment file; these are not generic
NNTP credentials. Pagination remains off. Actual EasyNews searches and paid
access have not been validated.

Three disposable native-profile checks passed against the exact published
AIOStreams image: anime presets with a compatible fixture account, direct
EasyNews with fixture account details, and disabled unsupported presets without
accounts. Generated manifests were checked; no stream searches were made with
fixture credentials. Tests retain the native rate limits and pace profile API
requests accordingly. Coverage/latency comparisons for these new anime sources
remain outstanding, which is why they are not enabled by default.
