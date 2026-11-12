# AIO Local Deployment Support Matrix

This document provides verified deployment patterns, platform compatibility, and player integration test results for **AIO Local** across container orchestrators, NAS appliances, and reverse proxy / tunneling architectures.

---

## 1. Verified Deployment Support Matrix

| Host Environment | Architecture | Orchestrator / Tool | Profile Tested | Pinned Bundle | Custom Ports (`PORT_*`) | Reverse Proxy / Ingress | Players Verified | Watch Tracking (SlickSync) | Rollback & Restore | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **Ubuntu 22.04 / 24.04 LTS** | `x86_64` | Docker Compose v2.27+ | `core`, `scrapers`, `nuvio` | `13855052857` | Verified | Traefik, Caddy, Nginx | Stremio Web (`:8082`), Nuvio (`:8085`), Desktop | Trakt, Simkl, AniList | Verified (zero data loss) | **Tier 1 (Production)** |
| **Debian 12 (Bookworm)** | `x86_64` | Dockge v1.4+ | `scrapers`, `nuvio` | `13855052857` | Verified | Cloudflare Tunnel | Stremio Web (`:8082`), Android TV | Trakt, Simkl | Verified | **Tier 1 (Production)** |
| **TrueNAS SCALE 24.04+** | `x86_64` | Portainer CE / Custom App | `scrapers` | `13855052857` | Verified | Built-in Ingress | Stremio Web, Stremio Mobile | Trakt | Verified | **Tier 1 (Production)** |
| **Synology DSM 7.2+** | `x86_64` | Container Manager (Compose) | `core` | `13855052857` | Verified | Synology Reverse Proxy | Stremio Web (`:8082`), Nuvio | Trakt, Simkl | Verified | **Tier 1 (Production)** |
| **Unraid 6.12+** | `x86_64` | Compose Manager Plugin | `scrapers` | `13855052857` | Verified | SWAG / Nginx Proxy Manager | Stremio Web, Desktop, Mobile | Trakt, Simkl, AniList | Verified | **Tier 1 (Production)** |
| **Raspberry Pi 5 (8 GB)** | `aarch64` | Docker Compose v2.27+ | `core` | Pending ARM release | Verified | Cloudflare Tunnel | Stremio Web (`:8082`) | Trakt | Verified | **Tier 2 (Preview)** |
| **Oracle Cloud Ampere A1** | `aarch64` | Dockge / Compose | `core` | Pending ARM release | Verified | Caddy Reverse Proxy | Stremio Web, Desktop | Trakt | Verified | **Tier 2 (Preview)** |

---

## 2. Deploying with Portainer (CE / Business)

### Method A: Web Editor (Recommended for Pinned Release)
1. In Portainer, navigate to **Stacks** → **Add Stack**.
2. Name the stack (e.g. `aio-local`).
3. Select **Web editor** and paste the contents of [`compose.manager.yml`](../compose.manager.yml).
4. Under **Environment variables**, click **Load variables from .env** and paste your `.env` configuration (or provide `ADDON_PASSWORD`, `BASE_URL`, and any provider API keys).
5. (Optional) Custom Ports: Specify any host port overrides in the environment section:
   ```env
   PORT_PORTAL=8088
   PORT_AIOSTREAMS=3001
   PORT_STREMIO_WEB=18082
   PORT_NUVIO=18085
   ```
6. Click **Deploy the stack**.
7. Access the Setup Portal at `http://<your-server-ip>:8088`.

---

## 3. Deploying with Dockge

1. In Dockge, click **+ Compose** to create a new stack named `aio-local`.
2. Paste [`compose.manager.yml`](../compose.manager.yml) into the Docker Compose editor.
3. In the `.env` editor pane on the right:
   ```env
   ADDON_PASSWORD=your_secure_password
   BASE_URL=http://your-server-ip:3001
   AIOMETADATA_HOST=http://your-server-ip:4005
   ```
4. Click **Deploy**. Dockge handles image pulling, volume initialization, and container start order with live health indicators.

---

## 4. Custom Port Mapping (`PORT_<SERVICE>`)

All published host ports in `compose.manager.yml` can be customized without editing the Compose YAML:

| Variable | Default Port | Internal Service | Portal Link Behavior |
|---|---:|---|---|
| `PORT_PORTAL` | `8088` | Appliance Setup Portal | Access address |
| `PORT_AIOSTREAMS` | `3001` | AIOStreams Aggregator & BuiltinProxy | Manifest & stream URLs |
| `PORT_AIOMETADATA` | `4005` | AIOMetadata Catalogs & Ratings | Catalog manifest URL |
| `PORT_STREMIO_WEB` | `8082` | Stremio Web Player | Setup portal launcher button (`Launch Stremio Web`) |
| `PORT_NUVIO` | `8085` | Nuvio Web Player | Setup portal launcher button (`Launch Nuvio Web`) |
| `PORT_SLICKSYNC` | `8086` | SlickSync Trakt Hub | SlickSync dashboard |
| `PORT_COMET` | `8000` | Comet Torrent Crawler | Internal bind IP |
| `PORT_ZILEAN` | `8181` | Zilean DMM Hash Cache | Internal bind IP |
| `PORT_PROWLARR` | `9696` | Prowlarr Indexer Manager | Internal bind IP |
| `PORT_SUBSENSE` | `3100` | SubSense Subtitles | Internal bind IP |

The Setup Portal (`:8088`) inspects runtime environment variables and dynamically points the frontend web player links (`Launch Stremio Web` and `Launch Nuvio Web`) to the exact custom ports configured on the host.

---

## 5. Reverse Proxy & Tunneling Verification

### Ingress Architectures Tested:
1. **Cloudflare Tunnel (`cloudflared`)**:
   - Zero open inbound ports required on the host router.
   - Routes public subdomains to internal container ports:
     - `aio.yourdomain.com` → `http://aiostreams:3000` (or host `:3001`)
     - `meta.yourdomain.com` → `http://aiometadata:4005`
     - `portal.yourdomain.com` → `http://portal:8088`
   - Authentication: Protected by `ADDON_PASSWORD` access key verification.
2. **Reverse Proxy (Traefik / Caddy / Nginx)**:
   - WebSocket and HTTP 206 Partial Content headers (`Range`, `Accept-Ranges`) pass through transparently.
   - Buffering disabled for streaming paths (`proxy_buffering off;`) to eliminate latency.

---

## 6. Watch Tracking (SlickSync) Reconnect & Survivability

- **SlickSync Hub (`:8086`)** stores OAuth tokens and scrobble state in the persistent named volume `slicksync-data` (`/app/data`).
- **Survives Container Restarts & Updates**: Token refresh cycles for Trakt.tv and Simkl remain active across container recreations without prompting the user to re-authorize.
- **Backup & Rollback Integration**: `tools/backup.py` includes `slicksync-data` in automated tar snapshots. Restoring a prior release backup recovers all linked accounts seamlessly.
