# Portal Improvement Roadmap

**Current Version:** v1.6.0  
**Product Goal:** A single-page appliance dashboard for configuring provider keys, launching the AIOStreams web player, exporting takeaway manifests, and managing self-hosted services via internal proxy.

---

## Architecture Principles

- **Single Ingress:** Only AIOStreams (`:3001`) and AIOMetadata (`:4005`) are exposed externally for remote streaming. All background daemons and database services bind to `127.0.0.1` on `stremio-net`.
- **Zero-Exposure Embedded Management:** Upstream service web dashboards (Prowlarr, InfiniDysk, Posters+, StremThru, Anime Kitsu) are accessed through the portal's authenticated reverse proxy (`/service-proxy/<service>/`) without opening extra host ports.
- **Atomic Operations:** Configuration saves and container provisioning use file-locking and scalar validation to prevent corruption.

---

## Roadmap Milestones

### 1. Unified Setup & Manifest Generator
*Status: Completed*
- Single-page setup covering Debrid, Usenet, metadata keys (TMDB, TVDB), and admin password.
- Instant 1-click generation of personalized AIOStreams and AIOMetadata manifest URLs.
- Clear separation between saved configuration, service reachability, and verified media playback.

### 2. Embedded Service Proxy & Fleet Status
*Status: Completed*
- Reverse proxy embedding internal service dashboards directly inside portal modals.
- Real-time container health, CPU/RAM resource monitoring, and PostgreSQL database initialization status.
- Safe cache cleanup with explicit user confirmation.

### 3. Usenet & Multi-Provider Ingress
*Status: Completed*
- Dedicated Usenet (NNTP) configuration for InfiniDysk on-demand streaming.
- Automated Prowlarr Newznab indexer synchronization.
- Automatic cross-protocol failover between Debrid and Usenet sources.

### 4. Consolidated Logs & Diagnostics
*Status: Completed*
- Real-time log streaming viewer with service selection and auto-follow mode.
- Non-destructive stream diagnostics verifying manifest endpoints and HTTP 206 Partial Content byte ranges.
- Built-in AniSkip intro/outro timestamp resolution endpoint (`/api/aniskip`).

### 5. Automated Backup & Disaster Recovery
*Status: Completed*
- Atomic full-stack backups covering SQLite databases, `.env`, and PostgreSQL dumps (`pg_dumpall`).
- Safe restore pipeline validating archive structure and rejecting path traversals.
- Diagnostic support bundle export with sensitive keys redacted.

### 6. Visual Theming & Design System
*Status: In Progress*
- CSS custom property design tokens for colors, spacing, and semantic status indicators (`ok`, `warn`, `error`, `info`).
- Persistent dark / light theme toggle (`data-theme`) adhering to user preference.
- Mobile viewport refinement for iOS and Android touch navigation.

### 7. Interactive Troubleshooting Assistant
*Status: Planned*
- In-portal diagnostic wizard guiding users through token renewals (Real-Debrid, TorBox, Trakt, Simkl).
- Automated DNS and tunnel reachability tester for remote streaming domains.
- Contextual error guidance linking playback timeouts directly to offending indexers or scraper logs.
