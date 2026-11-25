"""Bound indexer tests to the endpoint selected by the user."""
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from tools.usenet_config import newznab_endpoint, newznab_indexers


class NoIndexerRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Redirect targets must never inherit a saved credential.
        return None


OPENER = urllib.request.build_opener(NoIndexerRedirects())


def endpoint(value):
    return newznab_endpoint(value)


def validate_indexer(settings, key=None, url=None, indexer_id=None):
    try:
        target = endpoint(url or settings.get("NZB_INDEXER_URL") or "https://api.althub.co.za")
        clean_key = key.strip() if isinstance(key, str) else ""
        if not clean_key or clean_key.lower() == "saved":
            rows = newznab_indexers(settings)
            legacy = settings.get("USENET_EXTRA_INDEXERS", [])
            if isinstance(legacy, str):
                legacy = json.loads(legacy) if legacy.strip() else []
            if isinstance(legacy, list):
                rows += legacy
            clean_key = ""
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if indexer_id and str(row.get("id", "")) != str(indexer_id):
                    continue
                if endpoint(row.get("url", "")) != target:
                    continue
                clean_key = row.get("apiKey") or row.get("api_key") or row.get("key") or ""
                if clean_key:
                    break
        if not isinstance(clean_key, str) or not clean_key.strip():
            return {"status": "invalid", "detail": "No saved API key matches this indexer address. Save the address and key together, or enter a key to test."}
    except (ValueError, TypeError):
        return {"status": "invalid", "detail": "Enter a valid HTTP(S) indexer address without credentials, query parameters or fragments."}
    request = urllib.request.Request(
        target + "?t=caps&apikey=" + urllib.parse.quote(clean_key.strip(), safe=""),
        headers={"User-Agent": "AIO-Local/1.0", "Accept": "application/xml,text/xml"})
    try:
        with OPENER.open(request, timeout=8) as response:
            body = response.read(1048577)
        if len(body) > 1048576 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            raise ValueError("Invalid XML response")
        root = ET.fromstring(body)
        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "error":
            return {"status": "rejected", "detail": "Indexer rejected the capabilities request. Check the saved API key."}
        if tag != "caps":
            return {"status": "rejected", "detail": "Indexer did not return Newznab capabilities XML."}
        host = urllib.parse.urlsplit(target).netloc
        return {"status": "valid", "detail": f"NZB indexer ({host}) returned capabilities. Search authorization has not been tested."}
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            return {"status": "rejected", "detail": "Indexer redirected the test. Enter its final API address; saved keys are not forwarded to redirects."}
        return {"status": "rejected", "detail": f"Indexer returned HTTP {error.code}. Check its address and API key."}
    except (OSError, ValueError, ET.ParseError):
        return {"status": "unavailable", "detail": "Could not retrieve valid capabilities from this indexer."}
