#!/usr/bin/env bash
# ==============================================================================
# AIOStreams Self-Hosted Stack Management Script (Linux / Proxmox LXC)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

write_header() {
    echo -e "${CYAN}\n====================================================================${NC}"
    echo -e "  $1"
    echo -e "${CYAN}====================================================================${NC}"
}

ensure_directories() {
    echo -e "${CYAN}[i] Ensuring directory structures exist...${NC}"
    mkdir -p data/aiostreams \
             data/comet \
             data/mediafusion \
             data/prowlarr \
             data/subsense \
             data/sootio \
             data/redis \
             data/postgres \
             data/slicksync \
             data/aiometadata \
             data/postersplus \
             data/infinidysk \
             data/stremio-web \
             data/debrid-search \
             init/postgres \
             templates/setup-templates \
             templates/formatters \
             templates/filtering-and-expressions \
             templates/regex-rankings \
             templates/aiometadata-configs \
             templates/builtin
    chmod -R 777 data/slicksync data/aiometadata data/postersplus data/infinidysk data/stremio-web data/debrid-search data/sootio 2>/dev/null || true
    chmod +x init/postgres/init-databases.sh docker/sootio/*.js 2>/dev/null || true
    [ -f data/infinidysk/session.key ] && chmod 600 data/infinidysk/session.key 2>/dev/null || true
    echo -e "${GREEN}[✓] Directories ready.${NC}"
}

check_prerequisites() {
    write_header "Pre-Flight Diagnostics & Port Collision Check"

    if command -v docker &>/dev/null; then
        echo -e "${GREEN}[✓] Docker CLI detected: $(docker --version)${NC}"
    else
        echo -e "${RED}[✗] Docker CLI not found. Please install Docker.${NC}"
        return 1
    fi

    if docker info &>/dev/null; then
        echo -e "${GREEN}[✓] Docker daemon is running.${NC}"
    else
        echo -e "${YELLOW}[!] Docker daemon unreachable. Is the service active?${NC}"
    fi

    echo -e "${CYAN}[i] Testing port availability...${NC}"
    local ports=(3000 3001 3011 8000 8001 8181 9696 8191 8080 8888 7005 4005 3100 8085 8086 3005 8082 55771)
    local conflicts=0

    for port in "${ports[@]}"; do
        if ss -tuln 2>/dev/null | grep -q ":$port "; then
            echo -e "${YELLOW}[!] Port $port is already in use by another process.${NC}"
            ((conflicts++))
        else
            echo -e "  ✓ Port $port is available"
        fi
    done

    if [ "$conflicts" -eq 0 ]; then
        echo -e "${GREEN}[✓] All ports available without conflict.${NC}"
    else
        echo -e "${YELLOW}[!] $conflicts port conflict(s) detected.${NC}"
    fi
}

start_stack() {
    local profile="${1:-}"
    write_header "Starting Docker Compose Stack"
    ensure_directories
    if [ ! -f .env ] && [ -f .env.example ]; then
        echo -e "${YELLOW}[!] .env not found. Copying .env.example and generating unique security keys...${NC}"
        cp .env.example .env
        RAND_SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || od -vN 32 -An -tx1 /dev/urandom | tr -d ' \n')
        RAND_PG=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || od -vN 16 -An -tx1 /dev/urandom | tr -d ' \n')
        RAND_PROWLARR=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || od -vN 16 -An -tx1 /dev/urandom | tr -d ' \n')
        RAND_MEDIAFLOW=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || od -vN 16 -An -tx1 /dev/urandom | tr -d ' \n')
        RAND_POSTERS=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || od -vN 16 -An -tx1 /dev/urandom | tr -d ' \n')
        RAND_STREMTHRU=$(openssl rand -hex 16 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || od -vN 16 -An -tx1 /dev/urandom | tr -d ' \n')
        sed -i "s|SECRET_KEY=e2c019d4536f9a039b56f8f1dfba8919634e2c8846bb1999252c79213bc01b09|SECRET_KEY=${RAND_SECRET}|" .env
        sed -i "s|POSTGRES_PASSWORD=postgres_supersecret_db_pass_2026|POSTGRES_PASSWORD=${RAND_PG}|" .env
        sed -i "s|PROWLARR_API_KEY=prowlarr_internal_secret_key_99|PROWLARR_API_KEY=${RAND_PROWLARR}|" .env
        sed -i "s|MEDIAFLOW_PASS=supersecretmediaflowpass|MEDIAFLOW_PASS=${RAND_MEDIAFLOW}|" .env
        sed -i "s|POSTERSPLUS_ACCESS_KEY=admin|POSTERSPLUS_ACCESS_KEY=${RAND_POSTERS}|" .env
        sed -i "s|STREMTHRU_PROXY_AUTH_PASSWORD=admin|STREMTHRU_PROXY_AUTH_PASSWORD=${RAND_STREMTHRU}|" .env
        echo -e "${GREEN}[✓] Generated unique cryptographic keys across all internal services.${NC}"
    fi

    if [ -n "$profile" ]; then
        echo -e "${CYAN}[i] Launching with profile: ${profile}...${NC}"
        docker compose --profile "$profile" up -d
    else
        docker compose up -d
    fi
    echo -e "${GREEN}[✓] Docker stack started.${NC}"
    show_links
}

stop_stack() {
    write_header "Stopping Docker Compose Stack"
    docker compose down
    echo -e "${GREEN}[✓] Stack stopped.${NC}"
}

show_status() {
    write_header "Stack Status"
    docker compose ps
}

show_links() {
    write_header "Stremio Manifest & Service URLs"
    BASE_URL="https://aio.yourdomain.com"
    if [ -f .env ]; then
        VAL=$(grep -E '^BASE_URL=' .env | cut -d '=' -f2-)
        [ -n "$VAL" ] && BASE_URL="$VAL"
    fi

    echo -e "${GREEN}Central AIOStreams Addon Manifest:${NC}"
    echo -e "  ${BASE_URL}/manifest.json\n"

    echo -e "${CYAN}Web Management Portals:${NC}"
    echo -e "  • Appliance Hub (Landing Page): http://localhost:8088"
    echo -e "  • AIOStreams Portal:     http://localhost:3001"
    echo -e "  • Stremio Web Player:    http://localhost:8082"
    echo -e "  • Nuvio Web Player:      http://localhost:8085"
    echo -e "  • SlickSync Hub:         http://localhost:8086"
    echo -e "  • Debrid Cloud Search:   http://localhost:3011"
    echo -e "  • AIOMetadata:           http://localhost:4005"
    echo -e "  • SubSense Subtitles:    http://localhost:3100"
    echo -e "  • InfiniDysk Usenet:     http://localhost:3005"
    echo -e "  • Comet Scraper:         http://localhost:8000"
    echo -e "  • MediaFusion:           http://localhost:8001"
    echo -e "  • Sootio Multi-Scraper:  http://localhost:55771"
    echo -e "  • Anime Kitsu:           http://localhost:7005"
    echo -e "  • Prowlarr Indexers:     http://localhost:9696"
    echo -e "  • Zilean Hash Cache:     http://localhost:8181"
    echo -e "  • StremThru Proxy UI:    http://localhost:8080"
    echo -e "  • MediaFlow Proxy:       http://localhost:8888"
    echo -e "  • Hidden Cinemeta:       https://hidden-cinemeta.vercel.app/\n"

    echo -e "${YELLOW}Cinemeta Removal (Optional External Tool):${NC}"
    echo -e "  1. Visit Hidden Cinemeta: https://hidden-cinemeta.vercel.app/"
    echo -e "     (Hosted Fallback: https://hidden-cinemeta.vercel.app/ | Source: https://github.com/Skarian/hidden-cinemeta)"
    echo -e "  2. Input your Stremio AuthKey to hide Cinemeta's cloud catalogs."
    echo -e "  3. AIOMetadata (:4005) serves as your primary local rich metadata & catalog provider.\n"
}

cli_wizard() {
    write_header "Interactive CLI Configuration Wizard"
    ensure_directories

    local cur_base="https://aio.yourdomain.com"
    local cur_tmdb=""
    local cur_rd=""
    local cur_tvdb=""
    local cur_pm=""
    local cur_ad=""
    local cur_tb=""
    local cur_dl=""
    local cur_fa=""
    local cur_rp=""
    local cur_md=""
    local cur_ge=""
    local cur_pass="admin"
    local cur_sec=""
    local cur_pg=""
    local cur_prowl=""
    local cur_strem=""
    local cur_mf=""

    if [ -f .env ]; then
        cur_base=$(grep -E '^BASE_URL=' .env | cut -d '=' -f2- || echo "$cur_base")
        cur_tmdb=$(grep -E '^TMDB_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_rd=$(grep -E '^REALDEBRID_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_tvdb=$(grep -E '^TVDB_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_pm=$(grep -E '^PREMIUMIZE_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_ad=$(grep -E '^ALLDEBRID_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_tb=$(grep -E '^TORBOX_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_dl=$(grep -E '^DEBRIDLINK_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_fa=$(grep -E '^FANART_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_rp=$(grep -E '^RPDB_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_md=$(grep -E '^MDBLIST_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_ge=$(grep -E '^GEMINI_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_pass=$(grep -E '^ADDON_PASSWORD=' .env | cut -d '=' -f2- || echo "admin")
        cur_sec=$(grep -E '^SECRET_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_pg=$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d '=' -f2- || echo "")
        cur_prowl=$(grep -E '^PROWLARR_API_KEY=' .env | cut -d '=' -f2- || echo "")
        cur_strem=$(grep -E '^STREMTHRU_AUTH=' .env | cut -d '=' -f2- || echo "")
        cur_mf=$(grep -E '^MEDIAFLOW_PASS=' .env | cut -d '=' -f2- || echo "")
    fi

    read -p "AIOStreams Public Domain / Base URL [$cur_base]: " inp_base
    [ -n "$inp_base" ] && cur_base="$inp_base"

    read -p "TMDB v3 API Key [$cur_tmdb]: " inp_tmdb
    [ -n "$inp_tmdb" ] && cur_tmdb="$inp_tmdb"

    read -p "TheTVDB v4 API Key [$cur_tvdb]: " inp_tvdb
    [ -n "$inp_tvdb" ] && cur_tvdb="$inp_tvdb"

    read -p "Real-Debrid API Token [$cur_rd]: " inp_rd
    [ -n "$inp_rd" ] && cur_rd="$inp_rd"

    # Retain or generate random secrets
    [ -z "$cur_sec" ] && cur_sec=$(openssl rand -hex 32 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')
    [ -z "$cur_pg" ] && cur_pg="pg_$(openssl rand -hex 12 2>/dev/null || date +%s%N)"
    [ -z "$cur_prowl" ] && cur_prowl="prow_$(openssl rand -hex 12 2>/dev/null || date +%s%N)"
    [ -z "$cur_strem" ] && cur_strem="admin:$(openssl rand -hex 8 2>/dev/null || date +%s)"
    [ -z "$cur_mf" ] && cur_mf="mf_$(openssl rand -hex 10 2>/dev/null || date +%s)"

    cat <<EOF > .env
# ==============================================================================
#                      ALL-IN-ONE LOCAL STREMIO BACKEND (.env)
# ==============================================================================
BASE_URL=${cur_base}
TMDB_API_KEY=${cur_tmdb}
REALDEBRID_API_KEY=${cur_rd}
PREMIUMIZE_API_KEY=${cur_pm}
ALLDEBRID_API_KEY=${cur_ad}
TORBOX_API_KEY=${cur_tb}
DEBRIDLINK_API_KEY=${cur_dl}
TVDB_API_KEY=${cur_tvdb}
FANART_API_KEY=${cur_fa}
RPDB_API_KEY=${cur_rp}
MDBLIST_API_KEY=${cur_md}
GEMINI_API_KEY=${cur_ge}
ADDON_PASSWORD=${cur_pass}

SECRET_KEY=${cur_sec}
POSTGRES_PASSWORD=${cur_pg}
PROWLARR_API_KEY=${cur_prowl}
POSTERSPLUS_ACCESS_KEY=${cur_pass}
ADMIN_EMAIL=admin@mediafusion.local
STREMTHRU_AUTH=${cur_strem}
MEDIAFLOW_PASS=${cur_mf}

# ==============================================================================
# COMMUNITY TEMPLATES & STREAM EXPRESSION LANGUAGE (SEL) AUTO-SYNC
# ==============================================================================
TEMPLATE_URLS=["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/Tamtaro-All-Templates-for-AIOStreams.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/refs/heads/main/all-templates.json"]
TEMPLATE_REFRESH_INTERVAL=3600
WHITELISTED_SYNC_REFRESH_INTERVAL=3600
FEATURED_TEMPLATE_IDS=tamtaro.complete,Vidhin05.regex-template,Vidhin05.english-template
SEL_SYNC_ACCESS=all
WHITELISTED_REGEX_PATTERNS_URLS=["https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/regexes.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/German/regexes.json"]
WHITELISTED_SEL_URLS=["https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ESEs-extended.json","https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ESEs-standard.json","https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-ISEs.json","https://raw.githubusercontent.com/Tam-Taro/SEL-Filtering-and-Sorting/refs/heads/main/AIOStreams-SyncedURLs/Tamtaro-synced-PSEs.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/expressions.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/German/expressions.json","https://raw.githubusercontent.com/Vidhin05/Releases-Regex/main/English/legacy-expressions.json"]
EOF

    echo -e "${GREEN}[✓] .env written.${NC}"

    mkdir -p init/postgres
    cat <<EOF > init/postgres/01-init-dbs.sql
SELECT 'CREATE DATABASE zilean' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zilean')\gexec
SELECT 'CREATE DATABASE mediafusion' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mediafusion')\gexec
SELECT 'CREATE DATABASE aiometadata' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aiometadata')\gexec
EOF
    echo -e "${GREEN}[✓] init/postgres/01-init-dbs.sql written.${NC}"

    read -p "Start Docker stack now? (y/n) [y]: " start_now
    if [ "$start_now" != "n" ]; then
        start_stack
    fi
}

build_appliance() {
    echo -e "${CYAN}====================================================================${NC}"
    echo -e "  Building All-In-One Appliance Image (GHCR / Local)"
    echo -e "${CYAN}====================================================================${NC}"
    docker build -t aiostreams-aio:latest -t ghcr.io/ooflyeyesoo/aiostreams-aio:latest -f ./docker/all-in-one/Dockerfile .
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}[✓] Appliance image successfully built!${NC}"
        echo -e "Local tags:"
        echo -e "  • aiostreams-aio:latest"
        echo -e "  • ghcr.io/ooflyeyesoo/aiostreams-aio:latest"
    else
        echo -e "${RED}[✗] Build failed.${NC}"
    fi
}

case "$1" in
    wizard) cli_wizard ;;
    check)  check_prerequisites ;;
    start)  start_stack "$2" ;;
    stop)   stop_stack ;;
    status) show_status ;;
    links)  show_links ;;
    build)  build_appliance ;;
    *)
        while true; do
            echo -e "${CYAN}====================================================================${NC}"
            echo -e "  AIOStreams Stack Control (Linux / LXC)"
            echo -e "${CYAN}====================================================================${NC}"
            echo -e " 1) Interactive Setup Wizard"
            echo -e " 2) Run Pre-Flight Diagnostics & Port Collision Check"
            echo -e " 3) Start Stack (docker compose up -d)"
            echo -e " 4) View Stack Status (docker compose ps)"
            echo -e " 5) Stop Stack (docker compose down)"
            echo -e " 6) View Stremio Manifest & Service URLs"
            echo -e " 7) Build All-In-One Appliance Docker Package (ghcr.io/ooflyeyesoo/aiostreams-aio)"
            echo -e " 0) Exit"
            read -p "Select option [1-7, 0]: " opt
            case "$opt" in
                1) cli_wizard ;;
                2) check_prerequisites ;;
                3) start_stack ;;
                4) show_status ;;
                5) stop_stack ;;
                6) show_links ;;
                7) build_appliance ;;
                0) exit 0 ;;
                *) echo "Invalid option." ;;
            esac
        done
        ;;
esac
