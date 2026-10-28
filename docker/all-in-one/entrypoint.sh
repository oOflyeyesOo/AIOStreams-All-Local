#!/bin/bash
set -e

echo "=================================================================="
echo "    AIOStreams 100% Self-Hosted All-In-One Streaming Appliance    "
echo "=================================================================="

# Disable TLS generation inside dind to prevent "sed: write error" in LXC/nested environments
export DOCKER_TLS_CERTDIR=""
export PYTHONUNBUFFERED=1

# 1. Setup persistent storage & runtime directories
mkdir -p /data/aiostreams \
         /data/comet \
         /data/mediafusion \
         /data/prowlarr \
         /data/subsense \
         /data/sootio \
         /data/stremthru \
         /data/mediaflow \
         /data/redis \
         /data/postgres \
         /data/slicksync \
         /data/aiometadata \
         /data/postersplus \
         /data/infinidysk \
         /data/stremio-web \
         /data/debrid-search \
         /var/log \
         /etc/docker \
         /etc/containerd \
         /var/lib/docker

chmod -R 777 /data /data/slicksync /data/aiometadata /data/postersplus /data/infinidysk /data/stremio-web /data/debrid-search /data/sootio 2>/dev/null || true
[ -f /app/init/postgres/init-databases.sh ] && chmod +x /app/init/postgres/init-databases.sh 2>/dev/null || true
[ -f /data/infinidysk/session.key ] && chmod 600 /data/infinidysk/session.key 2>/dev/null || true

# Link /app/data to /data if external volume mounted to /data
if [ -d "/data" ]; then
    rm -rf /app/data 2>/dev/null || true
    ln -s /data /app/data
fi

# 2. Prevent containerd 10-second hang on ZFS in Proxmox LXC containers
# In LXC on ZFS, containerd attempts to query /dev/zfs which hangs for 10s,
# causing dockerd's internal healthcheck to timeout ("timeout waiting for containerd").
cat <<'EOF' > /etc/containerd/config.toml
version = 2
disabled_plugins = [
  "io.containerd.snapshotter.v1.zfs",
  "io.containerd.snapshotter.v1.aufs",
  "io.containerd.snapshotter.v1.btrfs",
  "io.containerd.snapshotter.v1.devmapper",
  "io.containerd.snapshotter.v1.blockfile"
]
EOF

# Mask any zfs binary so containerd probes return immediately (<0.001s)
for zpath in /usr/sbin/zfs /sbin/zfs /usr/bin/zfs /bin/zfs $(which -a zfs 2>/dev/null || true); do
    if [ -e "$zpath" ] || [ "$zpath" = "/usr/sbin/zfs" ]; then
        mkdir -p "$(dirname "$zpath")"
        cat <<'EOF' > "$zpath"
#!/bin/sh
exit 1
EOF
        chmod +x "$zpath" 2>/dev/null || true
    fi
done

# Clean any stale sockets/pid files from previous container restarts
rm -f /var/run/docker.pid \
      /var/run/docker/containerd/containerd.pid \
      /var/run/docker/containerd/containerd.sock \
      /var/run/containerd/containerd.sock \
      /run/docker.pid \
      /run/containerd/containerd.sock 2>/dev/null || true

# 3. Launch Appliance Web Portal on port 8088 FIRST
echo "[1/4] Starting built-in Appliance Web Portal & Setup on port 8088..."
python3 -u /app/docker/all-in-one/portal_server.py > /var/log/portal_server.log 2>&1 &
PORTAL_PID=$!
sleep 1
if kill -0 $PORTAL_PID 2>/dev/null; then
    echo "      Appliance Web Portal running on port 8088 (PID: $PORTAL_PID)."
else
    echo "[!] Portal server failed to start. View /var/log/portal_server.log:"
    cat /var/log/portal_server.log 2>/dev/null || true
fi

# 4. Launch internal Docker daemon (DinD) with smart fallback for LXC / ZFS
echo "[2/4] Starting internal container runtime engine..."

DOCKERD_PID=""
start_dockerd() {
    local driver="$1"
    local extra_args="--dns=1.1.1.1 --dns=8.8.8.8"
    if [ -n "$driver" ]; then
        extra_args="$extra_args --storage-driver=$driver"
        echo "      Starting container daemon with --storage-driver=$driver..."
    else
        echo "      Starting container daemon (auto-detect driver)..."
    fi
    dockerd-entrypoint.sh dockerd $extra_args > /var/log/dockerd.log 2>&1 &
    DOCKERD_PID=$!
}

# Start dockerd initially
start_dockerd ""

echo "      Waiting for container daemon readiness..."
retries=0
max_retries=90
attempted_vfs=false
daemon_ready=false

while [ $retries -lt $max_retries ]; do
    if docker info > /dev/null 2>&1; then
        echo "      Container daemon ready in ${retries}s."
        daemon_ready=true
        break
    fi

    # Check if dockerd process exited unexpectedly
    if [ -n "$DOCKERD_PID" ] && ! kill -0 $DOCKERD_PID 2>/dev/null; then
        echo "[!] Container daemon process exited. Last 15 log lines:"
        tail -n 15 /var/log/dockerd.log 2>/dev/null || true

        # If primary driver failed, retry once with vfs driver
        if [ "$attempted_vfs" != "true" ]; then
            echo "[i] Retrying container engine with fallback vfs storage driver..."
            attempted_vfs=true
            start_dockerd "vfs"
            retries=0
            sleep 2
            continue
        fi
        echo "[ERROR] Container daemon failed to start with available storage drivers."
        break
    fi

    sleep 1
    retries=$((retries + 1))
done

# 5. Handle stack startup if daemon is ready
if [ "$daemon_ready" = "true" ]; then
    cd /app
    if [ ! -f .env ] && [ -f .env.example ]; then
        echo "[3/4] Initializing .env configuration from template..."
        cp .env.example .env
    fi

    # Inject runtime environment variables if passed via -e or --env-file
    if [ -n "$BASE_URL" ]; then
        sed -i "s|^BASE_URL=.*|BASE_URL=${BASE_URL}|" .env
        if [ -z "$MEDIAFUSION_HOST_URL" ]; then
            MF_PROTO=$(echo "$BASE_URL" | sed -E 's|^(https?)://.*|\1|')
            [ -z "$MF_PROTO" ] && MF_PROTO="http"
            MF_HOST=$(echo "$BASE_URL" | sed -E 's|^https?://([^/:]+).*|\1|')
            if [ -n "$MF_HOST" ] && [ "$MF_HOST" != "localhost" ] && [ "$MF_HOST" != "127.0.0.1" ]; then
                if [ "$MF_PROTO" = "https" ]; then
                    export MEDIAFUSION_HOST_URL="${BASE_URL}"
                else
                    export MEDIAFUSION_HOST_URL="${MF_PROTO}://${MF_HOST}:8001"
                fi
                if grep -q "^MEDIAFUSION_HOST_URL=" .env; then
                    sed -i "s|^MEDIAFUSION_HOST_URL=.*|MEDIAFUSION_HOST_URL=${MEDIAFUSION_HOST_URL}|" .env
                else
                    echo "MEDIAFUSION_HOST_URL=${MEDIAFUSION_HOST_URL}" >> .env
                fi
            fi
        fi
    fi
    if [ -n "$MEDIAFUSION_HOST_URL" ]; then
        if grep -q "^MEDIAFUSION_HOST_URL=" .env; then
            sed -i "s|^MEDIAFUSION_HOST_URL=.*|MEDIAFUSION_HOST_URL=${MEDIAFUSION_HOST_URL}|" .env
        else
            echo "MEDIAFUSION_HOST_URL=${MEDIAFUSION_HOST_URL}" >> .env
        fi
    fi
    if [ -n "$TMDB_API_KEY" ]; then
        sed -i "s|^TMDB_API_KEY=.*|TMDB_API_KEY=${TMDB_API_KEY}|" .env
    fi
    if [ -n "$REALDEBRID_API_KEY" ]; then
        sed -i "s|^REALDEBRID_API_KEY=.*|REALDEBRID_API_KEY=${REALDEBRID_API_KEY}|" .env
    fi
    if [ -n "$PREMIUMIZE_API_KEY" ]; then
        sed -i "s|^PREMIUMIZE_API_KEY=.*|PREMIUMIZE_API_KEY=${PREMIUMIZE_API_KEY}|" .env
    fi
    if [ -n "$ALLDEBRID_API_KEY" ]; then
        sed -i "s|^ALLDEBRID_API_KEY=.*|ALLDEBRID_API_KEY=${ALLDEBRID_API_KEY}|" .env
    fi
    if [ -n "$TORBOX_API_KEY" ]; then
        sed -i "s|^TORBOX_API_KEY=.*|TORBOX_API_KEY=${TORBOX_API_KEY}|" .env
    fi
    if [ -n "$DEBRIDLINK_API_KEY" ]; then
        sed -i "s|^DEBRIDLINK_API_KEY=.*|DEBRIDLINK_API_KEY=${DEBRIDLINK_API_KEY}|" .env
    fi
    if [ -n "$TVDB_API_KEY" ]; then
        sed -i "s|^TVDB_API_KEY=.*|TVDB_API_KEY=${TVDB_API_KEY}|" .env
    fi
    if [ -n "$FANART_API_KEY" ]; then
        sed -i "s|^FANART_API_KEY=.*|FANART_API_KEY=${FANART_API_KEY}|" .env
    fi
    if [ -n "$RPDB_API_KEY" ]; then
        sed -i "s|^RPDB_API_KEY=.*|RPDB_API_KEY=${RPDB_API_KEY}|" .env
    fi
    if [ -n "$MDBLIST_API_KEY" ]; then
        sed -i "s|^MDBLIST_API_KEY=.*|MDBLIST_API_KEY=${MDBLIST_API_KEY}|" .env
    fi
    if [ -n "$GEMINI_API_KEY" ]; then
        sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${GEMINI_API_KEY}|" .env
    fi
    if [ -n "$ADDON_PASSWORD" ]; then
        sed -i "s|^ADDON_PASSWORD=.*|ADDON_PASSWORD=${ADDON_PASSWORD}|" .env
    fi
    if [ -n "$SECRET_KEY" ]; then
        sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" .env
    fi

    # Clean any stale or orphaned containers inside appliance from previous restarts
    echo "      Clearing any stale containers and dead port allocations..."
    docker compose down --remove-orphans 2>/dev/null || true
    docker rm -f $(docker ps -aq) 2>/dev/null || true

    # Start compose stack (exclude portal container since portal_server.py is already active on port 8088)
    echo "[4/4] Starting all streaming services and local scrapers..."
    docker compose up -d --scale portal=0 --remove-orphans

    # Auto-provision stack (Prowlarr trackers + MediaFusion default admin) in background
    if [ -f /app/init/bootstrap/setup_stack.py ]; then
        python3 -u /app/init/bootstrap/setup_stack.py > /var/log/stack_setup.log 2>&1 &
    elif [ -f /app/init/prowlarr/setup_prowlarr.py ]; then
        python3 -u /app/init/prowlarr/setup_prowlarr.py > /var/log/prowlarr_setup.log 2>&1 &
    fi

    echo ""
    echo "=================================================================="
    echo " [✓] All services active and running inside All-In-One container! "
    echo "=================================================================="
    echo " • Appliance Web Portal:   http://localhost:8088"
    echo " • AIOStreams Portal:     http://localhost:3001"
    echo " • Stremio Web Player:    http://localhost:8082"
    echo " • Nuvio Web Player:      http://localhost:8085"
    echo " • SlickSync Hub:         http://localhost:8086"
    echo " • Hidden Cinemeta:       https://hidden-cinemeta.vercel.app/"
    echo " • Debrid Cloud Search:   http://localhost:3011"
    echo " • AIOMetadata:           http://localhost:4005"
    echo " • Posters+:              http://localhost:9039"
    echo " • SubSense Subtitles:    http://localhost:3100"
    echo " • InfiniDysk Usenet:     http://localhost:3005"
    echo " • MediaFusion Scraper:   http://localhost:8001"
    echo " • Comet Scraper:         http://localhost:8000"
    echo " • Sootio Multi-Scraper:  http://localhost:55771"
    echo " • Anime Kitsu:           http://localhost:7005"
    echo " • Prowlarr Indexers:     http://localhost:9696"
    echo " • Zilean Hash Cache:     http://localhost:8181"
    echo " • StremThru Proxy UI:    http://localhost:8080"
    echo " • MediaFlow Proxy:       http://localhost:8888"
    echo "=================================================================="
    echo ""

    cleanup() {
        echo ""
        echo "[!] Stopping all stack services cleanly..."
        docker compose down
        [ -n "$PORTAL_PID" ] && kill $PORTAL_PID 2>/dev/null || true
        [ -n "$DOCKERD_PID" ] && kill $DOCKERD_PID 2>/dev/null || true
        echo "[✓] All services halted."
        exit 0
    }
    trap cleanup SIGTERM SIGINT

    # Stream aggregator logs to container stdout
    docker compose logs -f aiostreams
else
    echo "=================================================================="
    echo " [!] Internal container engine is still initializing or needs     "
    echo "     privileges. Web Portal remains active on port 8088.          "
    echo "=================================================================="

    cleanup_idle() {
        echo ""
        echo "[!] Shutting down appliance..."
        [ -n "$PORTAL_PID" ] && kill $PORTAL_PID 2>/dev/null || true
        [ -n "$DOCKERD_PID" ] && kill $DOCKERD_PID 2>/dev/null || true
        exit 0
    }
    trap cleanup_idle SIGTERM SIGINT

    # Keep container alive so web portal on port 8088 stays online and accessible
    tail -f /var/log/portal_server.log /var/log/dockerd.log
fi
