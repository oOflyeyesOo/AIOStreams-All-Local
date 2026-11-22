"""Prepare portable metadata presets without importing another user's identity."""
import copy
import urllib.parse
import urllib.request
import urllib.error
import json
import socket


KEY_FIELDS = {
    "tmdb": "TMDB_API_KEY", "tvdb": "TVDB_API_KEY", "fanart": "FANART_API_KEY",
    "mdblist": "MDBLIST_API_KEY", "rpdb": "RPDB_API_KEY", "gemini": "GEMINI_API_KEY",
}


def prepare_metadata_template(template, settings, existing=None):
    config = copy.deepcopy(template)
    existing = existing or {}
    if not isinstance(config, dict):
        raise ValueError("Metadata preset must contain an object")
    # Credentials belong to this installation/profile, never to a downloaded preset.
    keys = copy.deepcopy(existing.get("apiKeys") or {})
    for field, name in KEY_FIELDS.items():
        # Empty deployment defaults must not erase keys saved in the service UI.
        if str(settings.get(name) or "").strip():
            keys[field] = settings[name]
    config["apiKeys"] = keys
    for field in ("sessionId", "configHash", "configVersion", "lastModified",
                  "userUUID", "uuid"):
        config.pop(field, None)
    for field in ("tokens", "accounts", "oauth", "linkedAccounts", "jellyfinUsers",
                  "simklUser"):
        config.pop(field, None)
        if field in existing:
            config[field] = copy.deepcopy(existing[field])
    if not str(keys.get("fanart") or "").strip():
        for kind, providers in config.get("artProviders", {}).items():
            if providers == "fanart":
                config["artProviders"][kind] = "tmdb"
            elif isinstance(providers, dict):
                for slot, provider in list(providers.items()):
                    if provider == "fanart":
                        providers[slot] = "tmdb"
    if not str(keys.get("gemini") or "").strip():
        config.setdefault("search", {})["ai_enabled"] = False
    for catalog in config.get("catalogs", []):
        source = str(catalog.get("source", catalog.get("id", ""))).lower()
        if "mdblist" in source and not keys.get("mdblist"):
            catalog["enabled"] = False
        if "simkl" in source and "personal" in source and not keys.get("simklTokenId"):
            catalog["enabled"] = False
    poster_key = settings.get("POSTERSPLUS_ACCESS_KEY") or settings.get("ADDON_PASSWORD") or "admin"
    poster_base = settings.get("POSTERSPLUS_CONTAINER_URL") or "http://postersplus:8000"
    configured_poster = settings.get("POSTERSPLUS_URL")
    if configured_poster and "127.0.0.1" not in configured_poster and "localhost" not in configured_poster:
        poster_base = configured_poster
    poster_url = poster_base.rstrip("/") + "/poster?stremio_id={id}&type={type}&shape={shape}"
    poster_url += "&access_key=" + urllib.parse.quote(poster_key, safe="")
    config["customPosterUrl"] = poster_url
    config.setdefault("customArt", {}).update({"posterUrl": poster_url, "proxy": True})
    config["usePosterProxy"] = True
    return config


def metadata_error(status, body=None):
    """Return useful errors without forwarding upstream URLs, credentials or HTML."""
    body = body if isinstance(body, dict) else {}
    missing = body.get("missingKeys")
    labels = [key.upper() if key != "fanart" else "Fanart" for key in KEY_FIELDS
              if isinstance(missing, list) and key in missing]
    if status == 400 and labels:
        return "Save the required API key(s) before applying this preset: " + ", ".join(labels) + "."
    if status == 400 and "maxCatalogs" in body:
        return "This preset exceeds AIOMetadata's enabled catalog limit. Adjust the limit or choose a smaller preset."
    return {
        400: "AIOMetadata rejected the preset settings. Review the preset in its dashboard.",
        401: "AIOMetadata refused the saved profile or addon password. Check the stack password and existing profile password.",
        403: "AIOMetadata denied permission to update this profile.",
        404: "The saved AIOMetadata profile or API endpoint was not found. Check the profile in its dashboard.",
        409: "The metadata profile changed during this request. Reload and retry.",
        504: "AIOMetadata did not finish in time. Check its status before retrying; the update may still complete.",
    }.get(status, "AIOMetadata is unavailable or returned an invalid response. Check its service logs.")


class MetadataRequestError(Exception):
    def __init__(self, status, body=None):
        self.upstream_status = status
        super().__init__(metadata_error(status, body))


def request_metadata(url, data, method="POST"):
    request = urllib.request.Request(url, data=json.dumps(data).encode(),
                                     method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read(8192))
        except (ValueError, OSError):
            body = {}
        raise MetadataRequestError(error.code, body) from None
    except (TimeoutError, socket.timeout):
        raise MetadataRequestError(504) from None
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        is_dns = isinstance(reason, socket.gaierror) or any(
            ind in str(reason).lower()
            for ind in ("usable address", "not known", "getaddrinfo", "gaierror", "errno -5", "errno -2")
        )
        if is_dns or isinstance(reason, (ConnectionRefusedError, OSError)):
            parsed = urllib.parse.urlsplit(url)
            if (parsed.hostname or "").lower() == "aiometadata":
                fallback_url = urllib.parse.urlunsplit(
                    (parsed.scheme or "http", "127.0.0.1:4005", parsed.path, parsed.query, parsed.fragment)
                )
                if fallback_url != url:
                    try:
                        fallback_req = urllib.request.Request(
                            fallback_url, data=json.dumps(data).encode(),
                            method=method, headers={"Content-Type": "application/json"}
                        )
                        with urllib.request.urlopen(fallback_req, timeout=30) as response:
                            result = json.load(response)
                            if isinstance(result, dict) and result.get("success") is True:
                                return result
                    except Exception:
                        pass
        status = 504 if isinstance(error.reason, (TimeoutError, socket.timeout)) else 502
        raise MetadataRequestError(status) from None
    except (OSError, ValueError):
        raise MetadataRequestError(502) from None
    if not isinstance(result, dict) or result.get("success") is not True:
        raise MetadataRequestError(502)
    return result
