"""Shared application service inventory for health checks and the setup portal."""

INTEGRATIONS = (
    ("AIOStreams", "aiostreams", 3000, "Core"),
    ("Comet", "comet", 8000, "Scrapers"),
    ("MediaFusion", "mediafusion", 8000, "Scrapers"),
    ("Sootio", "sootio", 55771, "Scrapers"),
    ("Prowlarr", "prowlarr", 9696, "Indexers"),
    ("FlareSolverr", "flaresolverr", 8191, "Indexers"),
    ("Zilean", "zilean", 8181, "Indexers"),
    ("AIOMetadata", "aiometadata", 4005, "Metadata"),
    ("Anime Kitsu", "anime-kitsu", 7000, "Metadata"),
    ("Posters+", "postersplus", 8000, "Metadata"),
    ("SubSense", "subsense", 3100, "Subtitles"),
    ("Debrid Search", "debrid-search", 3011, "Library"),
    ("InfiniDysk", "infinidysk", 3000, "Usenet"),
    ("StremThru", "stremthru", 8080, "Proxies"),
    ("MediaFlow", "mediaflow", 8888, "Proxies"),
    ("Stremio Web", "stremio-web", 8080, "Players"),
    ("Nuvio", "nuvio", 3000, "Players"),
    ("SlickSync", "slicksync", 3000, "Sync"),
)

TCP_PORTS = {host: port for _, host, port, _ in INTEGRATIONS}
APPLICATION_SERVICE_COUNT = len(INTEGRATIONS)
