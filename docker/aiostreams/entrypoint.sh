#!/bin/sh
set -e

# ==============================================================================
# AIOStreams Resilient Self-Healing Entrypoint
# ==============================================================================
# Protects AIOStreams from startup crashes due to malformed, quoted, or non-hex
# environment variables entered via Coolify / Docker Compose.
# ==============================================================================

# 1. Sanitize SECRET_KEY
# Strip quotes if present
case "$SECRET_KEY" in
  \"*\") SECRET_KEY="${SECRET_KEY%\"}"; SECRET_KEY="${SECRET_KEY#\"}" ;;
esac
case "$SECRET_KEY" in
  "'"*"'" ) SECRET_KEY="${SECRET_KEY%\'}"; SECRET_KEY="${SECRET_KEY#\'}" ;;
esac

# Validate 64-character hexadecimal pattern in pure POSIX sh
HEX="[0-9a-fA-F]"
HEX8="${HEX}${HEX}${HEX}${HEX}${HEX}${HEX}${HEX}${HEX}"
HEX16="${HEX8}${HEX8}"
HEX32="${HEX16}${HEX16}"
HEX64="${HEX32}${HEX32}"

case "$SECRET_KEY" in
  $HEX64)
    # Valid 64-character hex string
    export SECRET_KEY="$SECRET_KEY"
    ;;
  *)
    echo "[AIOStreams] ERROR: SECRET_KEY must contain exactly 64 hexadecimal characters. Fix .env; keep the existing key for existing data." >&2
    exit 1
    ;;
esac

# 2. Sanitize BASE_URL
case "$BASE_URL" in
  \"*\") BASE_URL="${BASE_URL%\"}"; BASE_URL="${BASE_URL#\"}" ;;
esac
case "$BASE_URL" in
  "'"*"'" ) BASE_URL="${BASE_URL%\'}"; BASE_URL="${BASE_URL#\'}" ;;
esac

if [ -n "$BASE_URL" ]; then
  case "$BASE_URL" in
    http://*|https://*)
      ;;
    *)
      echo "[AIOStreams] ℹ️ BASE_URL was missing protocol scheme ('$BASE_URL'). Auto-prepending https://" >&2
      BASE_URL="https://$BASE_URL"
      ;;
  esac
  # Strip trailing slash
  BASE_URL="${BASE_URL%/}"
  export BASE_URL="$BASE_URL"
else
  export BASE_URL="http://localhost:${PORT:-3000}"
fi

# 2b. Sanitize FORCE_PROXY_URL so scheme-less BASE_URL values do not break Zod URL validation
case "$FORCE_PROXY_URL" in
  \"*\") FORCE_PROXY_URL="${FORCE_PROXY_URL%\"}"; FORCE_PROXY_URL="${FORCE_PROXY_URL#\"}" ;;
esac
case "$FORCE_PROXY_URL" in
  "'"*"'" ) FORCE_PROXY_URL="${FORCE_PROXY_URL%\'}"; FORCE_PROXY_URL="${FORCE_PROXY_URL#\'}" ;;
esac
case "$FORCE_PROXY_URL" in
  ""|null|undefined)
    unset FORCE_PROXY_URL
    ;;
  http://*|https://*)
    FORCE_PROXY_URL="${FORCE_PROXY_URL%/}"
    export FORCE_PROXY_URL="$FORCE_PROXY_URL"
    ;;
  *)
    FORCE_PROXY_URL="https://${FORCE_PROXY_URL%/}"
    export FORCE_PROXY_URL="$FORCE_PROXY_URL"
    ;;
esac

# 3. Sanitize ADDON_PASSWORD
case "$ADDON_PASSWORD" in
  \"*\") ADDON_PASSWORD="${ADDON_PASSWORD%\"}"; ADDON_PASSWORD="${ADDON_PASSWORD#\"}" ;;
esac
case "$ADDON_PASSWORD" in
  "'"*"'" ) ADDON_PASSWORD="${ADDON_PASSWORD%\'}"; ADDON_PASSWORD="${ADDON_PASSWORD#\'}" ;;
esac
if [ -z "$ADDON_PASSWORD" ]; then
  export ADDON_PASSWORD="admin"
else
  export ADDON_PASSWORD="$ADDON_PASSWORD"
fi

# 4. Ensure AIOSTREAMS_AUTH & PERMISSIONS are set
if [ -z "$AIOSTREAMS_AUTH" ]; then
  export AIOSTREAMS_AUTH="admin:$ADDON_PASSWORD"
fi
if [ -z "$AIOSTREAMS_AUTH_PERMISSIONS" ]; then
  export AIOSTREAMS_AUTH_PERMISSIONS="admin=admin"
fi

# 5. Locate Node.js binary (standard path in distroless image is /nodejs/bin/node)
if [ -x "/nodejs/bin/node" ]; then
  NODE_EXEC="/nodejs/bin/node"
elif command -v node >/dev/null 2>&1; then
  NODE_EXEC="node"
else
  NODE_EXEC="/nodejs/bin/node"
fi

# 6. Check for ALIASED_CONFIGURATIONS or auto-hydrate from persistent install metadata
case "$ALIASED_CONFIGURATIONS" in
  *null*|*undefined*|*": "*|*" :*"|"")
    unset ALIASED_CONFIGURATIONS
    ;;
esac

# Check for DEFAULT_AIO_UUID and DEFAULT_AIO_ENCRYPTED_PASSWORD in environment
if [ -z "$ALIASED_CONFIGURATIONS" ] && [ -n "$DEFAULT_AIO_UUID" ] && [ -n "$DEFAULT_AIO_ENCRYPTED_PASSWORD" ]; then
  case "$DEFAULT_AIO_UUID" in
    *-*-*-*-*)
      if [ "$DEFAULT_AIO_ENCRYPTED_PASSWORD" != "null" ] && [ "$DEFAULT_AIO_UUID" != "null" ]; then
        export ALIASED_CONFIGURATIONS="local:$DEFAULT_AIO_UUID:$DEFAULT_AIO_ENCRYPTED_PASSWORD"
        echo "[AIOStreams] 🔗 Auto-configured vanity alias 'local' from DEFAULT_AIO_UUID env ($DEFAULT_AIO_UUID)"
      fi
      ;;
  esac
fi

if [ -z "$ALIASED_CONFIGURATIONS" ]; then
  for candidate in /data/aiostreams_install.json /data/stremio-web/aiostreams_install.json /data/aiostreams/aiostreams_install.json; do
    if [ -f "$candidate" ]; then
      PAIR=""
      # Method A: Use Node.js if available (safe, robust JSON parsing, no external coreutils)
      if [ -x "$NODE_EXEC" ] || command -v node >/dev/null 2>&1; then
        PAIR=$(TARGET="$candidate" "$NODE_EXEC" -e '
          try {
            const fs = require("fs");
            const file = process.env.TARGET;
            const d = JSON.parse(fs.readFileSync(file, "utf8"));
            const uuid = typeof d.uuid === "string" ? d.uuid.trim() : "";
            const enc = typeof d.encrypted_password === "string" ? d.encrypted_password.trim() : (typeof d.encryptedPassword === "string" ? d.encryptedPassword.trim() : "");
            const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
            if (uuid && uuid !== "null" && enc && enc !== "null" && uuidRegex.test(uuid)) {
              process.stdout.write("local:" + uuid + ":" + enc);
            } else if (d.uuid === null || d.encrypted_password === null || d.uuid === "null") {
              try { fs.unlinkSync(file); } catch(err) {}
            }
          } catch (e) {}
        ' 2>/dev/null || true)
      fi

      # Method B: Pure POSIX shell line reader fallback (zero external binaries)
      if [ -z "$PAIR" ] && [ -f "$candidate" ]; then
        U=""
        E=""
        while IFS= read -r line || [ -n "$line" ]; do
          case "$line" in
            *\"uuid\":\ \"*\"*)
              val="${line#*\"uuid\": \"}"
              U="${val%%\"*}"
              ;;
            *\"encrypted_password\":\ \"*\"*)
              val="${line#*\"encrypted_password\": \"}"
              E="${val%%\"*}"
              ;;
            *\"encryptedPassword\":\ \"*\"*)
              val="${line#*\"encryptedPassword\": \"}"
              E="${val%%\"*}"
              ;;
          esac
        done < "$candidate"
        case "$U" in
          *-*-*-*-*)
            if [ -n "$E" ] && [ "$E" != "null" ]; then
              PAIR="local:$U:$E"
            fi
            ;;
        esac
      fi

      if [ -n "$PAIR" ]; then
        export ALIASED_CONFIGURATIONS="$PAIR"
        echo "[AIOStreams] Auto-configured vanity alias 'local' from persistent install metadata"
        break
      fi
    fi
  done
fi

# Final safety check: validate ALIASED_CONFIGURATIONS format before server launch
if [ -n "$ALIASED_CONFIGURATIONS" ]; then
  case "$ALIASED_CONFIGURATIONS" in
    *null*|*undefined*|*": "*|*" :*")
      echo "[AIOStreams] Unsetting malformed ALIASED_CONFIGURATIONS to prevent startup crash."
      unset ALIASED_CONFIGURATIONS
      ;;
    *:*:*)
      case "$ALIASED_CONFIGURATIONS" in
        *-*-*-*-*)
          # Valid UUID format detected
          ;;
        *)
          echo "[AIOStreams] Unsetting invalid ALIASED_CONFIGURATIONS - missing valid UUID."
          unset ALIASED_CONFIGURATIONS
          ;;
      esac
      ;;
    *)
      echo "[AIOStreams] Unsetting invalid ALIASED_CONFIGURATIONS - expected alias:uuid:password."
      unset ALIASED_CONFIGURATIONS
      ;;
  esac
fi

# 7. Unset empty optional variables to satisfy Zod schema validation and prevent startup crashes
case "$TRUSTED_IPS" in
  ""|null|undefined) unset TRUSTED_IPS ;;
esac

case "$FORCE_PROXY_ENABLED" in
  ""|null|undefined) unset FORCE_PROXY_ENABLED ;;
esac
case "$FORCE_PROXY_ID" in
  ""|null|undefined) unset FORCE_PROXY_ID ;;
esac
case "$FORCE_PROXY_CREDENTIALS" in
  ""|null|undefined) unset FORCE_PROXY_CREDENTIALS ;;
esac
case "$FORCE_PROXY_PROXIED_SERVICES" in
  ""|null|undefined) unset FORCE_PROXY_PROXIED_SERVICES ;;
esac

case "$DEFAULT_PROXY_URL" in
  ""|null|undefined) unset DEFAULT_PROXY_URL ;;
esac
case "$DEFAULT_PROXY_ID" in
  ""|null|undefined) unset DEFAULT_PROXY_ID ;;
esac
case "$DEFAULT_PROXY_CREDENTIALS" in
  ""|null|undefined) unset DEFAULT_PROXY_CREDENTIALS ;;
esac
case "$DEFAULT_PROXY_PROXIED_SERVICES" in
  ""|null|undefined) unset DEFAULT_PROXY_PROXIED_SERVICES ;;
esac
unset DEFAULT_PROXY_ENABLED

case "$DEFAULT_AIO_UUID" in
  ""|null|undefined) unset DEFAULT_AIO_UUID ;;
esac
case "$DEFAULT_AIO_ENCRYPTED_PASSWORD" in
  ""|null|undefined) unset DEFAULT_AIO_ENCRYPTED_PASSWORD ;;
esac

case "$TMDB_API_KEY" in
  ""|null|undefined) unset TMDB_API_KEY ;;
esac
case "$TVDB_API_KEY" in
  ""|null|undefined) unset TVDB_API_KEY ;;
esac
case "$MDBLIST_API_KEY" in
  ""|null|undefined) unset MDBLIST_API_KEY ;;
esac
case "$RPDB_API_KEY" in
  ""|null|undefined) unset RPDB_API_KEY ;;
esac
case "$FANART_API_KEY" in
  ""|null|undefined) unset FANART_API_KEY ;;
esac

# 8. Auto-redirect bare root (/) to embedded Web Player and (/admin) to (/dashboard)
if [ -x "$NODE_EXEC" ] || command -v node >/dev/null 2>&1; then
  "$NODE_EXEC" -e '
    try {
      const fs = require("fs");
      const file = "/app/packages/server/dist/app.js";
      if (fs.existsSync(file)) {
        let content = fs.readFileSync(file, "utf8");
        let modified = false;
        if (!content.includes("ROOT_REDIRECT_TO_PLAYER") && process.env.JELLYFIN_ENABLED !== "false" && process.env.AIO_ROOT_REDIRECT_TO_PLAYER !== "false") {
          content = content.replace(
            "app.get(\x27/configure\x27, (req, res) => {",
            "app.get(\x27/\x27, (req, res) => { res.redirect(302, \x27/jellyfin/web/\x27); }); // ROOT_REDIRECT_TO_PLAYER\napp.get(\x27/configure\x27, (req, res) => {"
          );
          modified = true;
          console.log("[AIOStreams] 🎬 Configured root (/) to default directly to Web Player (/jellyfin/web/)");
        }
        if (!content.includes("ADMIN_REDIRECT_TO_DASHBOARD")) {
          content = content.replace(
            "app.get(\x27/configure\x27, (req, res) => {",
            "app.get(\x27/admin\x27, (req, res) => { const q = req.url.includes(\x27?\x27) ? req.url.slice(req.url.indexOf(\x27?\x27)) : \x27\x27; res.redirect(302, \x27/dashboard\x27 + q); }); // ADMIN_REDIRECT_TO_DASHBOARD\napp.get(\x27/configure\x27, (req, res) => {"
          );
          modified = true;
          console.log("[AIOStreams] ⚙️ Configured (/admin) to route directly to (/dashboard)");
        }
        if (modified) {
          fs.writeFileSync(file, content, "utf8");
        }
      }
      const serverFile = "/app/packages/server/dist/server.js";
      if (fs.existsSync(serverFile)) {
        let sc = fs.readFileSync(serverFile, "utf8");
        const kaAnchor = sc.match(/attachJellyfinWebSocket\s*\(\s*server\s*\)\s*;/) || sc.match(/attachPartyRelay\s*\(\s*server\s*\)\s*;/);
        if (!sc.includes("AIO_KEEPALIVE_PATCH") && kaAnchor) {
          const kaLines = [
            "// AIO_KEEPALIVE_PATCH: prevent 502 keep-alive races behind Cloudflare Tunnel (90s default) and long-stream request timeouts",
            "const _kaMs = Number(process.env.AIO_KEEPALIVE_TIMEOUT_MS || 120000);",
            "const _hdrMs = Number(process.env.AIO_HEADERS_TIMEOUT_MS || 125000);",
            "const _reqMs = Number(process.env.AIO_REQUEST_TIMEOUT_MS || 0);",
            "if (Number.isFinite(_kaMs) && _kaMs > 0) server.keepAliveTimeout = _kaMs;",
            "if (Number.isFinite(_hdrMs) && _hdrMs > 0) server.headersTimeout = Math.max(_hdrMs, (server.keepAliveTimeout || 0) + 5000);",
            "if (Number.isFinite(_reqMs) && _reqMs >= 0) server.requestTimeout = _reqMs;",
            kaAnchor[0]
          ].join("\n        ");
          sc = sc.replace(kaAnchor[0], kaLines);
          fs.writeFileSync(serverFile, sc, "utf8");
          console.log("[AIOStreams] Tuned HTTP keepAliveTimeout=120s, headersTimeout=125s, requestTimeout=0 for proxy/stream stability");
        }
      }
    } catch (err) {}
  ' 2>/dev/null || true
fi

echo "[AIOStreams] 🚀 Starting server with validated SECRET_KEY (${#SECRET_KEY} chars) and BASE_URL: $BASE_URL"
exec "$NODE_EXEC" /app/packages/server/dist/server.js "$@"

