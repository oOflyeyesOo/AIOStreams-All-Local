# Routing and timing validation — 2026-11-07

## Request ownership

| Resource | Owner and path | Duplicate-work policy |
|---|---|---|
| Streams | Player → AIOStreams → native Comet and MediaFusion adapters; Debrid Search library | One combined player manifest |
| Indexer searches | Comet → search-broker → Prowlarr → indexers/FlareSolverr | Identical in-flight requests share one result; bounded concurrency/cache |
| DMM hash discovery | Comet → Zilean | MediaFusion Prowlarr/Zilean scraping and Sootio Zilean scraping disabled by default |
| Extra stream coverage | AIOStreams → Sootio | Sequential fallback only when primary results have no cached streams |
| Catalogs and metadata | AIOStreams → configured AIOMetadata; Kitsu for anime catalogs/metadata | Kitsu restricted to catalog/meta; unconfigured AIOMetadata omitted |
| Subtitles | AIOStreams → configured SubSense URL | Restricted to subtitles; configuration segment required |
| Artwork | AIOMetadata → Posters+ `/poster?stremio_id=…` | Explicit render key; portal password is not reused |
| Library | AIOStreams → Debrid Search | Catalog and stream resources only |
| Transport | AIOStreams built-in proxy; optional StremThru/MediaFlow | A second player-installed stream aggregator is not required |
| Usenet | Optional NZBDav/InfiniDysk path | Enabled credentials/infrastructure required; not live-tested here |

Installing both the combined manifest and its optional standalone metadata manifest
can duplicate catalogs. The page now says so. Public scrapers behind different
addons may still independently contact the same external sites: the policy above
does not establish global external-call deduplication.

`SOOTIO_MODE=fallback` is the new default; `off` omits it and `parallel` requests it
alongside primary sources. Earlier validation disabled Sootio entirely after long
timeouts. The new conditional fallback retains its observed episode coverage
without starting that work when cached primary streams already exist. Upstream
[addon groups documentation](https://github.com/Viren070/AIOStreams/blob/main/packages/docs/content/docs/guides/groups.mdx)
describes sequential execution; the tests below verify the actual installed server.

## Controlled actual-AIOStreams tests

`tests/check_routing_live.py` runs in a disposable portal and registers/removes its
own fixture profile. No provider keys or external scrapers are used. Primary delay
is 120 ms and fallback delay is 200 ms; these are routing budgets, not Internet
performance claims. Default upstream rate limits remain enabled; cases are paced.

| Case | Cold seconds | Warm seconds | Primary calls | Fallback calls |
|---|---:|---:|---:|---:|
| Movie, cached primary | 0.380 | 0.020 | 1 | 0 |
| Movie, empty primary | 0.340 | 0.010 | 1 | 1 |
| Episode, cached primary | 0.590 | 0.010 | 1 | 0 |
| Episode, empty primary | 0.740 | 0.010 | 1 | 1 |
| Primary HTTP 503 | 0.340 | 0.010 | 1 | 1 |

Four repeated concurrent viewers added zero fixture calls in every case.
Four simultaneous **cold** viewers completed in 140–142 ms with exactly one
primary call and zero fallback calls. Broker regression tests independently cover
eight simultaneous identical searches → one upstream call, credential isolation,
failure cooldown, admission capacity and cache byte/entry bounds.

The broker's default upstream socket timeout is 8 s and client wait budget 10 s;
failed requests have a 120 s cooldown. It cannot cancel work already running inside
Prowlarr. Different Torznab search forms are different requests and are not merged.
The 32 MiB cache and four-worker admission limit bound local work, not total memory
or CPU use across every application. Stronger upstream cancellation and pressure
tests remain on the roadmap.

## Read-only retained-installation timings

Windows Docker Desktop reference; existing caches were retained. Original keys
remained inside its running portal process. Configuration was not changed. These
measurements use the older installed parallel profile, not the candidate fallback
configuration. Initial observed aggregate responses were 17.499 s for a movie and
11.503 s for an episode; subsequent warm responses were 2.584 s and 1.409 s.
Neither run is a controlled empty-cache benchmark.

The repeat run confirmed movie/episode stream responses, native Comet results,
Sootio results and Kitsu anime metadata. Debrid Search and one episode Zilean
lookup returned HTTP 200 with no matching items; empty results are not proof of
service failure. Direct adapter counts use different filtering and warmed caches,
so they cannot rank sources by quality or comparable cold latency.

Two concrete integration errors were reproduced and fixed in candidate provisioning:
the old bare SubSense subtitle URL returned 404; a configured route returned
HTTP 200 with 208 subtitle entries. The old poster path returned 404; the corrected
query endpoint returned an image. Optional subtitle provider keys use upstream
configuration encryption when available and are never put in a plaintext fallback
URL.

Movie and episode origin reads returned HTTP 206 and 1,024 media bytes, with TTFB
1.343 s and 0.404 s. The original advertised public host is still the placeholder
`aio.yourdomain.com`; these reads deliberately used the internal AIOStreams address.
The range probes do not validate public DNS, a tunnel, Stremio Web playback or
decoding. A separate fresh FFmpeg check in the retained web-player container decoded
15 seconds of movie and episode audio/video successfully (exit 0), taking 6.565 s
and 10.215 s respectively. Candidate URLs traveled only in process memory/stdin;
no new credential-bearing candidate file was written. This used the same internal
address override and does not establish browser codec compatibility or public access.
StremThru and MediaFlow health endpoints passed; that alone is not transport playback.

## Tracing scope and repeatability

`tools/trace_proxy.py` now supports catalog/meta/subtitle/artwork/library edges and
per-port listeners for native adapters. `TRACE_EDGES_JSON` can declare, for example,
`[{"port":8101,"service":"comet","caller":"aiostreams"}]`; point that caller's
internal Comet origin at the listener without adding a URL prefix. Existing prefix
routes still work. Keep listeners internal, wait for events to finish before reset,
and read `/__trace/report`. Events contain caller, service, resource, elapsed time,
status and per-process HMAC target fingerprints; URLs, headers, queries and bodies
are not recorded. The buffer is capped at 10,000 events. Additional listener support
has forwarding/redaction regression coverage, but not every new edge has been
instrumented in a live external-provider run.

Remaining gates: true cold anime normalization, unavailable real indexers, memory
pressure, cancellation, authenticated tunnel and other paid-provider/NNTP accounts.
See [the roadmap](../ROADMAP.md); do not interpret these results as universal
duplicate-free traffic or every integration being end-to-end verified.
