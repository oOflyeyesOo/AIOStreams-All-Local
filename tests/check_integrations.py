"""Report configured optional integration adapters without exposing credentials."""
import os

PROVIDERS = (
    ("Real-Debrid", "REALDEBRID_API_KEY"),
    ("TorBox", "TORBOX_API_KEY"),
    ("AllDebrid", "ALLDEBRID_API_KEY"),
    ("Premiumize", "PREMIUMIZE_API_KEY"),
    ("Debrid-Link", "DEBRIDLINK_API_KEY"),
    ("EasyDebrid", "EASYDEBRID_API_KEY"),
    ("Offcloud", "OFFCLOUD_API_KEY"),
    ("Seedr", "SEEDR_API_KEY"),
)
METADATA = (
    ("TMDB", "TMDB_API_KEY"),
    ("TVDB", "TVDB_API_KEY"),
    ("Fanart.tv", "FANART_API_KEY"),
    ("MDBList", "MDBLIST_API_KEY"),
)


def main():
    configured_providers = [name for name, key in PROVIDERS if os.environ.get(key)]
    configured_metadata = [name for name, key in METADATA if os.environ.get(key)]
    if configured_providers:
        print("Configured provider adapters: " + ", ".join(configured_providers))
    else:
        print("SKIPPED: no debrid provider key configured.")
    print("Configured metadata adapters: " + (", ".join(configured_metadata) if configured_metadata else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
