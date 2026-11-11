# Images used by compose.manager.yml. No checkout or host-side build is needed.
FROM docker:29-cli AS portal
RUN apk add --no-cache python3
WORKDIR /app
COPY index.html dashboard.html .env.example compose.manager.yml /opt/aio/
COPY assets /opt/aio/assets
COPY templates /opt/aio/templates
COPY init /opt/aio/init
COPY tools /opt/aio/tools
COPY docker/all-in-one/portal_server.py /usr/local/lib/aio/portal_server.py
COPY docker/packaged/portal_entrypoint.py /usr/local/lib/aio/entrypoint.py
ENTRYPOINT ["python3", "-u", "/usr/local/lib/aio/entrypoint.py"]

FROM docker:29-cli AS controller
RUN apk add --no-cache python3
COPY docker/controller/controller.py /controller.py
COPY tools/release_manager.py /tools/release_manager.py
COPY tools/usenet_config.py /tools/usenet_config.py
ENTRYPOINT ["python3", "-u", "/controller.py"]

FROM ghcr.io/viren070/aiostreams:latest AS aiostreams
COPY docker/aiostreams/entrypoint.sh /entrypoint.sh
COPY templates/builtin /app/resources/templates

FROM tsaridas/stremio-docker:latest AS stremio-web
COPY docker/stremio-web/entrypoint.sh /aio-entrypoint.sh
COPY docker/stremio-web/bootstrap.js /srv/stremio-server/build/aio-bootstrap.js

FROM python:3.11-alpine AS bootstrap
COPY init/bootstrap /init
COPY init/service_inventory.py /init/service_inventory.py
COPY templates /templates
COPY tests/check_stack.py tests/check_streams.py tests/check_playback.py /

FROM postgres:16-alpine AS postgres-init
COPY init/postgres/init-databases.sh /init-databases.sh

FROM python:3.11-alpine AS search-broker
COPY tools/search_broker.py /search_broker.py
USER 65532:65532
ENTRYPOINT ["python3", "-u", "/search_broker.py"]
