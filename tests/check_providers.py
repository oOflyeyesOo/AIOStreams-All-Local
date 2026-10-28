"""Read-only provider authentication checks. Never prints credentials or responses."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def check(name, url, data=None):
    try:
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.load(response)
            success = bool(body.get("images")) if name == "TMDB" else bool(body.get("name")) if name == "Fanart" else body.get("status") in ("success", "ok")
            print(f"{name}: {'authentication passed' if success else 'authentication rejected'}")
    except urllib.error.HTTPError as error:
        print(f"{name}: HTTP {error.code} (credentials or account access rejected)")
    except Exception as error:
        print(f"{name}: request failed ({type(error).__name__})")


if __name__ == "__main__":
    key = os.environ.get("PREMIUMIZE_API_KEY")
    if key:
        check("Premiumize", "https://www.premiumize.me/api/account/info?" + urllib.parse.urlencode({"apikey": key}))
    key = os.environ.get("TMDB_API_KEY")
    if key:
        check("TMDB", "https://api.themoviedb.org/3/configuration?" + urllib.parse.urlencode({"api_key": key}))
    key = os.environ.get("TVDB_API_KEY")
    if key:
        check("TVDB", "https://api4.thetvdb.com/v4/login", json.dumps({"apikey": key}).encode())
    key = os.environ.get("FANART_API_KEY")
    if key:
        check("Fanart", "https://webservice.fanart.tv/v3/movies/550?" + urllib.parse.urlencode({"api_key": key}))
