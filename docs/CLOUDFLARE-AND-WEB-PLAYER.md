# Exposing the AIOStreams Web Player via Cloudflare Tunnel & Reverse Proxy

This guide explains how to expose the embedded **AIOStreams Web Player** for secure remote streaming anywhere in the world, while keeping **AIOMetadata, internal scrapers, databases, and admin portals 100% private and local**.

---

## 1. Architecture Overview: Single-Host vs Dual-Subdomain

| Feature | Mode 1: Web Player Ingress (Recommended) | Mode 2: Native Stremio Remote Addons |
| :--- | :--- | :--- |
| **Primary Use Case** | Browser playback on phones, tablets, laptops, TVs | Installing addons into standalone Stremio app remotely |
| **Public Hostnames Needed** | **1 Hostname** (e.g. `watch.yourdomain.com`) | **2 Hostnames** (`aio.yourdomain.com` & `aiometa.yourdomain.com`) |
| **Open Router Ports** | **0** (via Cloudflare Tunnel) | **0** (via Cloudflare Tunnel) |
| **AIOMetadata Exposure** | **Private & Local** (Internal Docker network only) | Exposed on Port 4005 |
| **Internal Scrapers (Zilean, Prowlarr)** | **Private & Local** | **Private & Local** |
| **Setup Portal (:8088)** | **Private & Local** (127.0.0.1 or LAN) | **Private & Local** |
| **Client Requirements** | Any modern web browser (WebGPU/HLS) | Stremio app |

### Why AIOMetadata Can Stay Local

When you use the embedded Web Player (`/jellyfin/web/`):
1. The browser connects **only** to AIOStreams (`http://aiostreams:3000` on port `3001`).
2. AIOStreams queries AIOMetadata (`http://aiometadata:4005`) **internally** across Docker's private bridge network (`stremio-net`).
3. Stream URLs and media metadata are resolved on the server and delivered directly to the Web Player.
4. **AIOMetadata never needs public exposure.** You do not need a second domain or complex routing rules.

---

## 2. Cloudflare Zero Trust Setup (Zero Router Ports, 2 Minutes)

Cloudflare Zero Trust Tunnels provide an encrypted outbound connection from your home server to Cloudflare's edge network. You do not need to open any ports on your home router, and it works seamlessly behind Carrier-Grade NAT (CGNAT).

### Step 1: Create a Tunnel in Cloudflare Dashboard
1. Log into your free Cloudflare account at [dash.cloudflare.com](https://dash.cloudflare.com).
2. In the left sidebar, navigate to **Zero Trust** (or go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com)).
3. Go to **Networks** &rarr; **Tunnels**.
4. Click **Add a tunnel** &rarr; select **Cloudflare (cloudflared)** &rarr; click **Next**.
5. Name your tunnel (e.g., `aio-player`) and click **Save tunnel**.

### Step 2: Copy Your Tunnel Token
Under the **Install and run a connector** step, look at the Docker run command. Locate the token string after `--token`:
```bash
cloudflared tunnel run --token eyJh...<YOUR_TOKEN_HERE>...
```
Copy just this token string (`eyJh...`).

### Step 3: Add the Token to `.env`
Open your `.env` file and set:
```bash
CLOUDFLARE_TUNNEL_TOKEN=eyJh...<YOUR_TOKEN_HERE>...
```

To automatically start the tunnel container whenever your stack boots, add `tunnel` to `COMPOSE_PROFILES`:
```bash
COMPOSE_PROFILES=scrapers,tunnel
```
Or start it manually:
```bash
docker compose --profile tunnel up -d
```
The `aio-tunnel` container will start and connect to Cloudflare immediately.

### Step 4: Configure the Public Hostname in Cloudflare
Back in the Cloudflare Zero Trust Dashboard under your tunnel:
1. Click the **Public Hostnames** tab &rarr; click **Add a public hostname**.
2. Fill in the hostname details:
   - **Subdomain:** `watch` (or `player` or `aio`)
   - **Domain:** `yourdomain.com` (select your Cloudflare-managed domain)
   - **Path:** leave blank
3. Under **Service**:
   - **Type:** `HTTP`
   - **URL:** `aiostreams:3000` (if using Docker network) or `localhost:3001`
4. Under **Additional application settings** &rarr; **HTTP Settings**:
   - Leave defaults (or toggle *No TLS Verify* if routing to HTTPS).
5. Click **Save hostname**.

### Step 5: Update Your Stack Configuration
In the AIO Setup Portal (`http://localhost:8088`):
1. Switch **Access Scope** to **Remote Access**.
2. Set **AIOStreams address**: `https://watch.yourdomain.com`
3. Leave **AIOMetadata address** as default (`http://localhost:4005` or blank).
4. Click **Connect my stack**.

---

## 3. Launching & Watching Remotely

Open your browser on any phone, tablet, laptop, or smart TV:
```
https://watch.yourdomain.com
```
*(Visiting the bare root domain automatically redirects straight into the embedded Web Player &mdash; no folders or multiple path layers required!)*

- **Username:** `admin`
- **Password:** Your `ADDON_PASSWORD` (configured in portal or `.env`)

### 1-Click Quick Connect for Smart TVs & Mobile Apps
If you use client apps such as **Infuse**, **Swiftfin**, **Findroid**, or **Kodi**:
1. Connect the app to server: `https://watch.yourdomain.com/jellyfin`
2. Select **Quick Connect**.
3. On your phone or laptop, navigate to:
   ```
   https://watch.yourdomain.com/jellyfin/quickconnect
   ```
4. Enter the 6-digit code displayed on your TV screen to authenticate instantly without typing passwords with a TV remote.

---

## 4. Built-in Root Redirection (No Subfolders Needed!)

The stack includes automatic root redirection (`AIO_ROOT_REDIRECT_TO_PLAYER=true` by default in `docker/aiostreams/entrypoint.sh`). When Jellyfin is enabled, opening `https://watch.yourdomain.com/` immediately redirects to the Web Player (`/jellyfin/web/`).

- **No Folder Typing:** You do not need to append `/jellyfin/web/` or multiple path layers. Simply bookmark and share `https://watch.yourdomain.com`.
- **Configurator Still Accessible:** If you ever want to reconfigure your addon directly, open `https://watch.yourdomain.com/configure` or click the **Configure** button on the local Setup Portal (`:8088`).
- **Admin Panel:** Open `https://watch.yourdomain.com/admin` to manage your streams, users, and caching.
- **Edge Reverse Proxy Overrides (Optional):** If you prefer your edge reverse proxy (Cloudflare, Caddy, Nginx) to handle the redirect before traffic hits the container:

### Cloudflare Redirect Rule (Free & Instant)
1. In Cloudflare Dashboard, go to your domain &rarr; **Rules** &rarr; **Redirect Rules**.
2. Click **Create rule**:
   - **Rule name:** `Root to Web Player`
   - **Incoming requests match:** Custom filter expression
   - **Expression:**
     ```
     (http.host eq "watch.yourdomain.com" and http.request.uri.path eq "/")
     ```
   - **Type:** Dynamic or Static
   - **Target URL:** `https://watch.yourdomain.com/jellyfin/web/`
   - **Status code:** `302`
3. Click **Deploy**. Now entering `watch.yourdomain.com` immediately launches the player!

---

## 5. Alternative Ingress Snippets (Caddy / Nginx / Traefik)

If you use an existing reverse proxy instead of Cloudflare Tunnel, use these single-host snippets:

### Caddy
```caddyfile
watch.yourdomain.com {
    # Auto-redirect root visits to the Web Player
    @root path /
    redir @root /jellyfin/web/ 302

    reverse_proxy aiostreams:3000
}
```

### Nginx
```nginx
server {
    server_name watch.yourdomain.com;
    listen 443 ssl http2;

    # Redirect root to Web Player
    location = / {
        return 302 /jellyfin/web/;
    }

    location / {
        proxy_pass http://aiostreams:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
```

### Traefik
```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.aiostreams.rule=Host(`watch.yourdomain.com`)
  - traefik.http.services.aiostreams.loadbalancer.server.port=3000
```

---

## 6. Security & Invariant Checklist

- [x] **No Open Ports on Router:** Cloudflare Tunnel operates entirely via outbound TLS connection.
- [x] **Single-IP Protection:** Debrid requests route through `FORCE_PROXY_PROXIED_SERVICES`, preserving your Real-Debrid / Premiumize single-IP account limits regardless of client location.
- [x] **Local Isolation:** Scrapers (Prowlarr, Zilean, StremThru, Bitmagnet) and databases (Postgres, Redis) remain strictly bound to `127.0.0.1` and the private `stremio-net` Docker network.
- [x] **Embedded Web Player Only:** Zero local media file storage, zero STRM generation, and strictly no Sonarr, Radarr, or Comet.
