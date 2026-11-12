import re
from pathlib import Path
import unittest

class PortalDOMTests(unittest.TestCase):
    def setUp(self):
        self.html = Path("index.html").read_text(encoding="utf-8")
        self.js = Path("assets/app.js").read_text(encoding="utf-8")

    def test_dom_ids_exist(self):
        js_ids = set(re.findall(r"document\.getElementById\(['\"]([^'\"]+)['\"]\)", self.js))
        html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', self.html))

        # Dynamic fields from app.js
        # Providers, metadata, trackingKeys, extras, optionalSecrets
        providers = ['PREMIUMIZE_API_KEY','REALDEBRID_API_KEY','TORBOX_API_KEY','ALLDEBRID_API_KEY','DEBRIDLINK_API_KEY','EASYDEBRID_API_KEY']
        metadata = ['TMDB_API_KEY','TVDB_API_KEY','FANART_API_KEY','MDBLIST_API_KEY','GEMINI_API_KEY']
        tracking = ['TRAKT_CLIENT_ID','TRAKT_CLIENT_SECRET','SIMKL_CLIENT_ID','SIMKL_CLIENT_SECRET','ANILIST_CLIENT_ID','ANILIST_CLIENT_SECRET']
        extras = ['RPDB_API_KEY','SUBDL_API_KEY','SUBSOURCE_API_KEY','WYZIE_API_KEY','OFFCLOUD_API_KEY','SEEDR_API_KEY']
        optional = ['NZB_INDEXER_API_KEY']
        dynamic_keys = set(providers + metadata + tracking + extras + optional)

        dynamic_suffixes = ['-saved', '-remove', '-test']
        missing = []

        for jid in sorted(js_ids):
            if jid in html_ids:
                continue
            # check if it's dynamic
            if jid in dynamic_keys:
                continue
            is_dyn = any(jid.endswith(s) and jid[:-len(s)] in dynamic_keys for s in dynamic_suffixes)
            if not is_dyn:
                missing.append(jid)

        print(f"Total JS element IDs checked: {len(js_ids)}")
        print(f"Missing from HTML: {missing}")
        self.assertEqual(missing, [], f"Found JS element references without matching HTML elements: {missing}")

    def test_templates_referenced_in_html_exist_on_disk(self):
        options = re.findall(r'<option\s+value="([^"]+\.json)"', self.html)
        self.assertGreater(len(options), 0, "No template JSON options found in HTML")
        for opt in options:
            template_path = Path("templates/aiometadata-configs") / opt
            self.assertTrue(template_path.is_file(), f"Template option in HTML does not exist: {template_path}")

    def test_html_tag_matching(self):
        # Verify critical containers are balanced
        for tag in ["form", "details", "section", "main", "body", "html"]:
            open_count = len(re.findall(rf'<{tag}[\s>]', self.html, re.IGNORECASE))
            close_count = len(re.findall(rf'</{tag}>', self.html, re.IGNORECASE))
            self.assertEqual(open_count, close_count, f"Unbalanced <{tag}>: {open_count} open vs {close_count} close")

if __name__ == "__main__":
    unittest.main()
