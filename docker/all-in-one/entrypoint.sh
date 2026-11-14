#!/bin/bash
set -e

echo "=================================================================="
echo "    AIOStreams 100% Self-Hosted All-In-One Streaming Appliance    "
echo "=================================================================="

# Disable TLS generation inside dind to prevent "sed: write error" in LXC/nested environments
export DOCKER_TLS_CERTDIR=""
export PYTHONUNBUFFERED=1
# The early portal is status-only. The functional portal runs on the Compose network.
export AIO_STARTUP_ONLY=true

# 1. Setup persistent storage & runtime directories
mkdir -p /data/aiostreams \
         /data/comet \
         /data/prowlarr \
         /data/subsense \
         /data/stremthru \
         /data/redis \
         /data/postgres \
         /data/slicksync \
         /data/aiometadata \
         /data/postersplus \
         /data/infinidysk \
         /data/stremio-web \
         /var/log \
         /etc/docker \
         /etc/containerd \
         /var/lib/docker

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
    # Preserve portal settings across image replacement; import explicit runtime
    # settings safely, including encoded NNTP credentials.
    python3 /app/docker/all-in-one/prepare_env.py

    # Build the patched services before starting them; do not silently use an
    # upstream image in place of a service with a local build definition.
    docker compose build

    # Stop only the temporary host-side portal before binding the real portal.
    # Never launch setup_stack.py on this host: Compose DNS is container-local.
    kill "$PORTAL_PID" 2>/dev/null || true
    wait "$PORTAL_PID" 2>/dev/null || true
    PORTAL_PID=""
    echo "[4/4] Starting services and the network-connected setup portal..."
    if docker compose up -d --scale stack-bootstrap=0 --wait --wait-timeout 600; then
        # Use the same controller action as the setup button. It applies the
        # saved environment and runs bootstrap inside the service network.
        if ! docker compose exec -T portal python3 -c 'import importlib.util; s=importlib.util.spec_from_file_location("portal", "/app/docker/all-in-one/portal_server.py"); p=importlib.util.module_from_spec(s); s.loader.exec_module(p); p.launch_setup()'; then
            echo "[!] Automatic setup could not start. Open the portal and choose Connect my stack."
        fi
    else
        echo "[ERROR] Service startup failed. Inspect inner Compose status and logs."
        # Keep a reachable status page if the real portal could not start.
        if ! curl -fsS http://127.0.0.1:8088/healthz >/dev/null 2>&1; then
            python3 -u /app/docker/all-in-one/portal_server.py > /var/log/portal_server.log 2>&1 &
            PORTAL_PID=$!
        fi
    fi

    echo ""
    echo "=================================================================="
    echo " Appliance started. Check portal readiness and setup progress. "
    echo "=================================================================="
    echo " â€¢ Appliance Web Portal:   http://localhost:8088"
    echo " â€¢ AIOStreams Portal:     http://localhost:3001"
    echo " â€¢ Stremio Web Player:    http://localhost:8082"
    echo " â€¢ Nuvio Web Player:      http://localhost:8085"
    echo " â€¢ SlickSync Hub:         http://localhost:8086"
    echo " â€¢ AIOMetadata:           http://localhost:4005"
    echo " â€¢ Posters+:              http://localhost:9039"
    echo " â€¢ SubSense Subtitles:    http://localhost:3100"
    echo " â€¢ InfiniDysk Usenet:     http://localhost:3005"
    echo " â€¢ Comet Scraper:         http://localhost:8000"
    echo " â€¢ Anime Kitsu:           http://localhost:7005"
    echo " â€¢ Prowlarr Indexers:     http://localhost:9696"
    echo " â€¢ Zilean Hash Cache:     http://localhost:8181"
    echo " â€¢ StremThru Proxy UI:    http://localhost:8080"
    echo "=================================================================="
    echo ""

    cleanup() {
        echo ""
        echo "[!] Stopping all stack services cleanly..."
        docker compose down
        [ -n "$PORTAL_PID" ] && kill $PORTAL_PID 2>/dev/null || true
        [ -n "$DOCKERD_PID" ] && kill $DOCKERD_PID 2>/dev/null || true
        echo "[âœ“] All services halted."
        exit 0
    }
    trap cleanup SIGTERM SIGINT

    # Stream aggregator logs to container stdout
    # Keep the supervisor alive even if an application exits or logs disconnect.
    while true; do sleep 5 & wait $!; done
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
