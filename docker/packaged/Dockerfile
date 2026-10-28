# Images used by compose.manager.yml. No checkout or host-side build is needed.
FROM python:3.11-alpine AS portal
WORKDIR /app
COPY index.html dashboard.html .env.example compose.manager.yml /opt/aio/
COPY assets /opt/aio/assets
COPY templates /opt/aio/templates
COPY docker/all-in-one/portal_server.py /usr/local/lib/aio/portal_server.py
COPY docker/packaged/portal_entrypoint.py /usr/local/lib/aio/entrypoint.py
ENTRYPOINT ["python3", "-u", "/usr/local/lib/aio/entrypoint.py"]

FROM docker:29-cli AS controller
RUN apk add --no-cache python3
COPY docker/controller/controller.py /controller.py
ENTRYPOINT ["python3", "-u", "/controller.py"]

FROM ghcr.io/viren070/aiostreams:latest AS aiostreams
COPY docker/aiostreams/entrypoint.sh /entrypoint.sh
COPY templates/builtin /app/resources/templates

FROM midnightignite1/sootio-stremio-addon:latest AS sootio
COPY docker/sootio/configuration.js /app/lib/util/configuration.js
COPY docker/sootio/landingTemplate.js /app/lib/util/landingTemplate.js

FROM tsaridas/stremio-docker:latest AS stremio-web
COPY docker/stremio-web/entrypoint.sh /aio-entrypoint.sh
COPY docker/stremio-web/bootstrap.js /srv/stremio-server/build/aio-bootstrap.js

FROM python:3.11-alpine AS bootstrap
COPY init/bootstrap /init
COPY templates /templates
COPY tests/check_stack.py tests/check_streams.py tests/check_playback.py /

FROM postgres:16-alpine AS postgres-init
COPY init/postgres/init-databases.sh /init-databases.sh
