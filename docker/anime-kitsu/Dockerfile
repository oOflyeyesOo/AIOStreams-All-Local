FROM node:22-alpine AS build
RUN apk add --no-cache git
WORKDIR /home/node/app
# Verified upstream source revision; review this pin when updating the patch.
ARG KITSU_REF=1420ccb02e0e3e9881c7614a47bad3ca41af830e
RUN git init . && git remote add origin https://github.com/TheBeastLT/stremio-kitsu-anime.git && \
    git fetch --depth=1 origin "$KITSU_REF" && git checkout --detach FETCH_HEAD && rm -rf .git
COPY docker/anime-kitsu/optional-fanart.cjs /tmp/optional-fanart.cjs
RUN node /tmp/optional-fanart.cjs && npm ci --omit=dev

FROM node:22-alpine
WORKDIR /home/node/app
COPY --from=build /home/node/app ./
CMD ["node", "index.js"]
