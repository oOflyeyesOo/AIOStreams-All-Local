FROM midnightignite1/sootio-stremio-addon:latest
COPY docker/sootio/bounded-curl.mjs /app/lib/util/bounded-curl.mjs
COPY docker/sootio/patch-scrapers.mjs /tmp/aio-patch-scrapers.mjs
RUN node /tmp/aio-patch-scrapers.mjs && rm /tmp/aio-patch-scrapers.mjs
COPY docker/sootio/configuration.js /app/lib/util/configuration.js
COPY docker/sootio/landingTemplate.js /app/lib/util/landingTemplate.js
