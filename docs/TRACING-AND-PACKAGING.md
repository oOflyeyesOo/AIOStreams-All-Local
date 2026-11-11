# Tracing and packaging — 2026-11-07

## Packaging evidence

All local manager images built successfully: portal, controller, AIOStreams, Stremio Web, bootstrap, PostgreSQL initializer and Kitsu. The generated manager definition validates. Packaged portal/controller started in project `aio-package` with named volumes and no source checkout; portal health, shared inventory imports, bootstrap imports and controller `/status` all passed. Custom Comet and metadata host ports survived portal reseeding. Cloudflare Tunnel remains optional. These are local images tagged `release-test`; they have not been published as final.

Regression suite: **77 passed**. Tests cover trace redaction/response forwarding and manager host-port persistence in addition to the earlier portal/bootstrap/backup coverage.

## Tracing findings

The instrument is an opt-in internal HTTP proxy. It never records request URLs, query strings, headers or response bodies. It covers only configured HTTP edges; it does not count encrypted external provider requests. Trace cases wait for unfinished requests to drain before resetting counters.

The streamlined stack excludes slow external crawlers, relying on Comet, Prowlarr, Byparr, and the Intelligent Search Broker. The Search Broker bounds request concurrency, eliminates duplicate upstream queries, and enforces a 60s in-memory cache to guarantee fast response times.

### Warm requests after the change

| Case | Attempt | Seconds | Stream URLs | Observed traced upstream calls |
|---|---:|---:|---:|---:|
| movie | 1 | 0.229 | 16 | 0 |
| movie | 2 | 0.168 | 16 | 0 |
| series | 1 | 0.585 | 1 | 0 |
| series | 2 | 0.078 | 1 | 0 |

Zero observed calls on these warm paths demonstrates cache reuse on the instrumented edges, not proof that every external service made zero calls. The earlier trace did not wait for late requests and is diagnostic evidence only, not an exact per-case count.

Movie and episode media each returned HTTP 206 with 65,536 bytes and both decoded for 15 seconds in the bundled web-player container. No duplicate stream URLs appeared in those acceptance responses.

Cold-request results are recorded below. Existing service/cache startup conditions differ from a brand-new installation. A complete manager-driven full-stack apply, release image publication, external request tracing and remaining integration acceptance gates are separate outstanding work.

## Cold-request observations

| Case | Attempt | Seconds to response | Stream URLs | Instrumented upstream calls |
|---|---:|---:|---:|---|
| movie | 1 | 8.179 | 16 | {'zilean': 1, 'prowlarr': 1} |
| movie | 2 | 0.175 | 16 | {} |
| series | 1 | 11.502 | 1 | {'prowlarr': 3, 'zilean': 1} |
| series | 2 | 0.646 | 1 | {} |

Cold cases used The Matrix and Game of Thrones S2E1. Multiple Prowlarr calls can represent distinct search forms; this instrument records counts/timings but deliberately does not retain the query text needed to classify exact query duplicates. Do not interpret these counts as a proof of duplicate-free external traffic.

### Identical-request check

A follow-up cold episode case (Game of Thrones S3E1) used per-process HMAC fingerprints of method, service and complete target. Only the one-way fingerprint is recorded; raw queries and configuration tokens are never logged.

- Attempt 1: 11.969 seconds, 10 stream URLs, 4 observed upstream calls, 0 identical repeated targets.
- Attempt 2: 0.134 seconds, 10 stream URLs, 0 observed upstream calls, 0 identical repeated targets.
