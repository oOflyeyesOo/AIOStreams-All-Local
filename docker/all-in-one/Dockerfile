FROM docker:27-dind

LABEL maintainer="oOflyeyesOo"
LABEL description="AIOStreams 100% Self-Hosted All-In-One Streaming Appliance Container"

# Disable TLS certificate generation to prevent sed write errors in nested/LXC environments
ENV DOCKER_TLS_CERTDIR=""

# Install runtime dependencies and compatibility drivers
RUN apk add --no-cache bash curl git jq python3 iptables && \
    (apk add --no-cache fuse-overlayfs || true)

WORKDIR /app

# Copy stack definitions and configuration files
COPY docker-compose.yml /app/docker-compose.yml
COPY .env.example /app/.env.example
COPY index.html /app/index.html
COPY dashboard.html /app/dashboard.html
COPY assets/ /app/assets/
COPY setup.sh /app/setup.sh
COPY init/ /app/init/
COPY templates/ /app/templates/
COPY docker/ /app/docker/

# Copy entrypoint script
COPY docker/all-in-one/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /app/setup.sh /app/docker/all-in-one/portal_server.py

# Expose all client and service ports
# 8088: Appliance Web Portal & Setup
# 3001: AIOStreams Super-Addon
# 8085: Nuvio Web Player
# 8086: SlickSync Hub
# 4005: AIOMetadata
# 9039: Posters+
# 3100: SubSense Subtitles
# 8000: Comet
# 8001: MediaFusion
# 55771: Sootio Multi-Scraper
# 7005: Anime Kitsu
# 8181: Zilean
# 3011: Debrid Search
# 3005: InfiniDysk Usenet WebDAV
# 8082: Stremio Web Player
# 8080: StremThru
# 8888: MediaFlow
# 9696: Prowlarr
EXPOSE 8088 3001 3011 3005 8082 8085 8086 4005 9039 3100 8000 8001 55771 7005 8181 9696 8080 8888

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
