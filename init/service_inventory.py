"""Shared application service inventory for health checks and the setup portal."""

INTEGRATIONS = (
    ("AIOStreams", "aiostreams", 3000, "Core"),
    ("Prowlarr", "prowlarr", 9696, "Indexers"),
    ("FlareSolverr", "flaresolverr", 8191, "Indexers"),
    ("Zilean", "zilean", 8181, "Indexers"),
    ("AIOMetadata", "aiometadata", 4005, "Metadata"),
    ("Anime Kitsu", "anime-kitsu", 7000, "Metadata"),
    ("Posters+", "postersplus", 8000, "Metadata"),
    ("SubSense", "subsense", 3100, "Subtitles"),
    ("StremThru", "stremthru", 8080, "Proxies"),
    ("LumiereDB", "lumiere-db", 8000, "Metadata"),
)

TCP_PORTS = {host: port for _, host, port, _ in INTEGRATIONS}
APPLICATION_SERVICE_COUNT = len(INTEGRATIONS)

# (container_port, default_host_port, env_port_var)
SERVICE_PORT_MAP = {
    "postersplus": (8000, 9039, "PORT_POSTERSPLUS"),
    "aiometadata": (4005, 4005, "PORT_AIOMETADATA"),
    "aiostreams": (3000, 3001, "PORT_AIOSTREAMS"),
    "prowlarr": (9696, 9696, "PORT_PROWLARR"),
    "flaresolverr": (8191, 8191, "PORT_FLARESOLVERR"),
    "zilean": (8181, 8181, "PORT_ZILEAN"),
    "stremthru": (8080, 8080, "PORT_STREMTHRU"),
    "subsense": (3100, 3100, "PORT_SUBSENSE"),
    "stremio-subsense": (3100, 3100, "PORT_SUBSENSE"),
    "anime-kitsu": (7000, 7005, "PORT_ANIME_KITSU"),
    "lumiere-db": (8000, 8000, "PORT_LUMIERE_DB"),
    "jikan-api": (8080, 8001, "PORT_JIKAN_API"),
}

SERVICE_CONTAINERS = {
    "subsense": "stremio-subsense",
}

# Profiles matching docker-compose.yml; None means always enabled.
SERVICE_PROFILES = {
    "aiostreams": None,
    "prowlarr": ("core", "scrapers", "all"),
    "flaresolverr": ("core", "scrapers", "all"),
    "zilean": ("core", "scrapers", "all"),
    "aiometadata": ("core", "scrapers", "all"),
    "anime-kitsu": ("anime", "anime-db", "scrapers", "all"),
    "postersplus": ("core", "scrapers", "all"),
    "subsense": ("core", "scrapers", "all"),
    "stremthru": ("core", "scrapers", "all"),
    "lumiere-db": ("core", "scrapers", "all"),
    "jikan-api": ("anime", "anime-db", "all"),
    "jikan-mongo": ("anime", "anime-db", "all"),
}

# Watchdog health probe specifications per inventoried service.
HEALTH_PROBES = {
    "aiostreams": {"path": "/manifest.json", "expected_code": [200], "critical": True, "host_exposed": True},
    "prowlarr": {"path": "/ping", "expected_code": [200], "critical": False, "host_exposed": True},
    "flaresolverr": {"path": "/", "expected_code": [200], "critical": False, "host_exposed": True},
    "zilean": {"path": "/dmm/filtered?query=ping", "expected_code": [200], "critical": False, "host_exposed": True},
    "aiometadata": {"path": "/health/live", "expected_code": [200], "critical": True, "host_exposed": True},
    "anime-kitsu": {"path": "/manifest.json", "expected_code": [200], "critical": False, "host_exposed": True},
    "postersplus": {"path": "/health", "expected_code": [200], "critical": False, "host_exposed": True},
    "subsense": {"path": "/", "expected_code": [200], "critical": False, "host_exposed": True},
    "stremthru": {"path": "/v0/health", "expected_code": [200], "critical": False, "host_exposed": True},
    "lumiere-db": {"path": "/health", "expected_code": [200], "critical": False, "host_exposed": False},
}


def parse_compose_profiles(raw_profiles):
    """Parse COMPOSE_PROFILES into normalized lowercase profile names."""
    cleaned = str(raw_profiles or "").split("#", 1)[0].strip().strip("\"'")
    profiles = set()
    for part in cleaned.split(","):
        token = part.strip().strip("\"'").lower()
        if not token:
            continue
        if token == "scrapers":
            profiles.update(("core", "scrapers"))
        elif token == "anime-db":
            profiles.update(("anime", "anime-db"))
        else:
            profiles.add(token)
    return profiles or {"core"}


def is_service_active(host, profiles=None):
    """Return True if a service host should be running for the active profiles."""
    allowed = SERVICE_PROFILES.get(host)
    if allowed is None:
        return True
    active = parse_compose_profiles(profiles) if not isinstance(profiles, (set, frozenset)) else (profiles or {"core"})
    return bool(active.intersection(allowed))


def active_service_hosts(profiles=None):
    """Return inventoried service hostnames enabled for the active Compose profiles."""
    active = parse_compose_profiles(profiles) if not isinstance(profiles, (set, frozenset)) else (profiles or {"core"})
    return [host for _, host, _, _ in INTEGRATIONS if is_service_active(host, active)]
