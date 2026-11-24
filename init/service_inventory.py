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
