import os
import json
os.environ["AIO_SKIP_ENV_FILE"] = "true"
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "bootstrap", Path(__file__).resolve().parents[1] / "init/bootstrap/setup_stack.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def test_prowlarr_provisioning_allows_scraping_and_debrid_to_finish(self):
        with patch.object(bootstrap, "PREMIUMIZE_API_KEY", "fixture-key"):
            config = bootstrap.build_default_config(probe_services=False)
        prowlarr = next(p for p in config["presets"] if p["instanceId"] == "prowlarr-scraper")
        self.assertEqual(prowlarr["options"]["sources"], ["torrent"])
        self.assertEqual(prowlarr["options"]["prowlarrUrl"], "http://prowlarr:9696")
        self.assertTrue(prowlarr["enabled"])

    def setUp(self):
        # Unit tests model availability explicitly; DNS/network delays belong in E2E checks.
        probe = patch.object(bootstrap, "is_url_reachable", return_value=True)
        probe.start()
        self.addCleanup(probe.stop)
        requests = patch.object(bootstrap, "make_request", return_value={})
        requests.start()
        self.addCleanup(requests.stop)

    def test_core_startup_failure_does_not_modify_profiles_or_indexers(self):
        with patch.object(bootstrap, "wait_for_aiostreams", return_value=False), patch.object(bootstrap, "setup_aiostreams_default_user") as configure, patch.object(bootstrap, "wait_for_prowlarr") as indexers:
            self.assertEqual(bootstrap.main(), 1)
            configure.assert_not_called()
            indexers.assert_not_called()

    def test_error_status_is_not_accepted_as_aiostreams_readiness(self):
        with patch.object(bootstrap, "make_request", return_value={"status": "error", "error": -1}), patch.object(bootstrap.time, "sleep"):
            self.assertFalse(bootstrap.wait_for_aiostreams(max_attempts=1, interval=0))

    def test_update_env_file_replaces_existing_key_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("BASE_URL=http://old.example\nBASE_URL=http://duplicate.example\n", encoding="utf-8")
            self.assertTrue(bootstrap.update_env_file(
                "BASE_URL", "https://new.example", candidates=[str(env_path)]
            ))
            self.assertEqual(env_path.read_text(encoding="utf-8"), "BASE_URL=https://new.example\n")

    def test_optional_metadata_is_skipped_when_dependencies_are_unavailable(self):
        with patch.object(bootstrap, "wait_for_postersplus", return_value=False), \
             patch.object(bootstrap, "wait_for_aiometadata") as wait_metadata, \
             patch.object(bootstrap, "setup_aiometadata_tamtaro") as configure_metadata:
            self.assertIsNone(bootstrap.setup_optional_metadata())
        wait_metadata.assert_not_called()
        configure_metadata.assert_not_called()

    def test_optional_metadata_configures_only_after_both_dependencies_are_ready(self):
        with patch.object(bootstrap, "wait_for_postersplus", return_value=True), \
             patch.object(bootstrap, "wait_for_aiometadata", return_value=True), \
             patch.object(bootstrap, "setup_aiometadata_tamtaro", return_value="http://aiometadata:4005/manifest.json") as configure_metadata:
            self.assertEqual(
                bootstrap.setup_optional_metadata(),
                "http://aiometadata:4005/manifest.json",
            )
        configure_metadata.assert_called_once_with()

    def test_prowlarr_indexer_setup_skips_existing_definitions(self):
        schemas = [
            {"definitionName": "1337x", "name": "1337x"},
            {"definitionName": "yts", "name": "YTS"},
        ]
        requests = []

        def request(url, method="GET", data=None, headers=None, timeout=12):
            if url.endswith("/api/v1/indexer") and method == "GET":
                return [{"definitionName": "1337x", "name": "Existing 1337x", "id": 7}]
            if url.endswith("/api/v1/indexer/schema"):
                return schemas
            if method == "POST":
                requests.append((url, data))
                return {"id": 8}
            raise AssertionError(f"Unexpected request: {method} {url}")

        with patch.object(bootstrap, "make_request", side_effect=request):
            with patch.object(bootstrap, "TARGET_INDEXERS", ["1337x", "yts"]):
                bootstrap.setup_prowlarr_indexers()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][1]["definitionName"], "yts")

    def test_error_entries_are_not_playable(self):
        self.assertEqual(bootstrap.playable_streams({"streams": [{"name": "Error", "title": "Invalid Api Key"}]}), [])
        self.assertEqual(bootstrap.playable_streams({"streams": [{"url": "https://comet.feels.legal/", "title": "Invalid Api Key"}]}), [])

    def test_readiness_rejects_truthy_error_responses(self):
        with patch.object(bootstrap, "make_request", return_value={"error": 503}), patch.object(bootstrap.time, "sleep"):
            self.assertFalse(bootstrap.wait_for_aiometadata(max_attempts=2, interval=0))

    def test_readiness_accepts_manifest(self):
        with patch.object(bootstrap, "make_request", return_value={"id": "metadata"}):
            self.assertTrue(bootstrap.wait_for_aiometadata(max_attempts=1))

    def test_metadata_save_supplies_addon_password_and_uses_install_path(self):
        response = {"success": True, "userUUID": "test-id", "installUrl": "http://localhost:4005/stremio/test-id/manifest.json"}
        with patch.dict(bootstrap.os.environ, {"AIOMETADATA_PROFILE_UUID": "", "FANART_API_KEY": "fixture-fanart", "SIMKL_CLIENT_ID": "my-simkl-client-id", "ANILIST_TOKEN": "my-anilist-token"}), patch.object(bootstrap, "make_request", return_value=response) as request, patch.object(bootstrap, "update_env_file"):
            result = bootstrap.setup_aiometadata_tamtaro()
            self.assertEqual(result, bootstrap.AIOMETADATA_URL + "/stremio/test-id/manifest.json")
            self.assertEqual(request.call_args.kwargs["data"]["addonPassword"], bootstrap.ADDON_PASSWORD)
            saved_config = request.call_args.kwargs["data"]["config"]
            self.assertNotIn("simklTokenId",saved_config["apiKeys"])
            self.assertNotIn("anilistTokenId",saved_config["apiKeys"])
            self.assertTrue(saved_config.get("traktWatchTracking"))
            self.assertTrue(saved_config.get("simklWatchTracking"))
            self.assertTrue(saved_config.get("anilistWatchTracking"))
            self.assertTrue(saved_config.get("malWatchTracking"))
            self.assertEqual(saved_config.get("artProviders", {}).get("anime", {}).get("logo"), "fanart")
            self.assertEqual(saved_config.get("animeEpisodeDates"), "earliest")

    def test_metadata_bootstrap_works_without_optional_artwork_and_ai_keys(self):
        response = {"success": True, "userUUID": "fixture"}
        env = {"AIOMETADATA_PROFILE_UUID": "", "TMDB_API_KEY": "fixture-tmdb", "FANART_API_KEY": "", "GEMINI_API_KEY": ""}
        with patch.dict(bootstrap.os.environ, env), \
             patch.object(bootstrap, "FANART_API_KEY", ""), patch.object(bootstrap, "GEMINI_API_KEY", ""), \
             patch.object(bootstrap, "make_request", return_value=response) as request, patch.object(bootstrap, "update_env_file"):
            bootstrap.setup_aiometadata_tamtaro()
        config = request.call_args.kwargs["data"]["config"]
        for kind in ("movie", "series", "anime"):
            self.assertEqual(config["artProviders"][kind]["logo"], "tmdb")
            self.assertEqual(config["artProviders"][kind]["background"], "tmdb")
        self.assertFalse(config["search"]["ai_enabled"])

    def test_metadata_save_error_names_missing_key_without_echoing_response(self):
        response = {"error": 400, "message": '{"missingKeys":["tmdb","private-data"],"error":"private-data"}'}
        with patch.dict(bootstrap.os.environ, {"AIOMETADATA_PROFILE_UUID": ""}), \
             patch.object(bootstrap, "make_request", return_value=response):
            with self.assertRaisesRegex(RuntimeError, r"^AIOMetadata needs an API key for TMDB\.$"):
                bootstrap.setup_aiometadata_tamtaro()

    def test_metadata_repeat_setup_preserves_linked_accounts(self):
        existing={"apiKeys":{"simklTokenId":"linked-simkl-record","anilistTokenId":"linked-anilist-record"}}
        responses=[{"success":True,"config":existing},{"success":True,"userUUID":"existing"}]
        with patch.dict(bootstrap.os.environ,{"AIOMETADATA_PROFILE_UUID":"existing","SIMKL_CLIENT_ID":"client-not-token"}), patch.object(bootstrap,"make_request",side_effect=responses) as request, patch.object(bootstrap,"update_env_file"):
            bootstrap.setup_aiometadata_tamtaro()
        payload=request.call_args.kwargs['data']['config']
        self.assertEqual(payload['apiKeys']['simklTokenId'],'linked-simkl-record')
        self.assertEqual(payload['apiKeys']['anilistTokenId'],'linked-anilist-record')
        self.assertEqual(request.call_args.kwargs['method'],'PUT')

    def test_metadata_load_failure_does_not_overwrite_existing_profile(self):
        with patch.dict(bootstrap.os.environ,{"AIOMETADATA_PROFILE_UUID":"existing"}), patch.object(bootstrap,"make_request",return_value={"error":401}) as request:
            with self.assertRaises(RuntimeError):bootstrap.setup_aiometadata_tamtaro()
        self.assertEqual(request.call_count,1)

    def test_metadata_rotation_preserves_existing_profile_and_catalogs(self):
        saved_catalogs = [{"id": "custom-catalog"}]
        config = {"catalogs": saved_catalogs, "apiKeys": {}}
        replies = [{"error": 401}, {"success": True, "config": config}, {"success": True},
                   {"success": True, "config": config}, {"success": True, "userUUID": "saved-profile"}]
        with patch.dict(bootstrap.os.environ, {"AIOMETADATA_PROFILE_UUID": "saved-profile", "AIO_PASSWORD_PREVIOUS": "before-password"}), \
             patch.object(bootstrap, "ADDON_PASSWORD", "after-password"), \
             patch.object(bootstrap, "make_request", side_effect=replies) as request, \
             patch.object(bootstrap, "update_env_file"):
            bootstrap.setup_aiometadata_tamtaro()
        reset = request.call_args_list[2]
        self.assertTrue(reset.args[0].endswith("/saved-profile/reset-password"))
        self.assertEqual(reset.kwargs["data"], {"newPassword": "after-password"})
        self.assertEqual(request.call_args.kwargs["data"]["config"]["catalogs"], saved_catalogs)

    def test_legacy_aiostreams_profile_rotation_returns_updated_link(self):
        replies = [{"error": 401}, {"error": 401}, {"success": True},
                   {"success": True, "data": {"encryptedPassword": "new-link-token"}}]
        with patch.dict(bootstrap.os.environ, {"AIO_PASSWORD_PREVIOUS": "before-password"}), \
             patch.object(bootstrap, "ADDON_PASSWORD", "after-password"), \
             patch.object(bootstrap, "make_request", side_effect=replies) as request:
            self.assertEqual(bootstrap.unlock_aiostreams_profile("saved-profile", "old-link-token"),
                             ("after-password", "new-link-token"))
        self.assertTrue(request.call_args.args[0].endswith("/user/password"))
        self.assertEqual(request.call_args.kwargs["data"], {"newPassword": "after-password"})

    def test_metadata_rejection_is_not_reported_as_saved(self):
        with patch.object(bootstrap, "make_request", return_value={"error": 401}):
            with self.assertRaises(RuntimeError):
                bootstrap.setup_aiometadata_tamtaro()

    def test_empty_and_failed_responses_are_not_playable(self):
        for value in ({"error": 500}, {"streams": []}, None):
            self.assertEqual(bootstrap.playable_streams(value), [])

    def test_playable_candidates_are_counted(self):
        response = {"streams": [{"url": "https://example.org/video.mp4"}, {"infoHash": "hash"}, {"title": "Error"}]}
        self.assertEqual(len(bootstrap.playable_streams(response)), 2)

    def test_core_smoke_cases_cover_movie_and_episode(self):
        self.assertEqual(
            bootstrap.CORE_SMOKE_CASES,
            (("movie", "tt1375666", "movie"), ("series", "tt0903747:1:1", "episode")),
        )

    def test_subtitles_use_configured_path_even_without_optional_keys(self):
        with patch.object(bootstrap,"make_request",return_value={}):
            config=bootstrap.build_default_config(probe_services=False)
        subtitle=next(p for p in config['presets'] if p['instanceId']=='subsense-local')
        self.assertNotEqual(subtitle['options']['manifestUrl'],'http://subsense:3100/manifest.json')
        self.assertEqual(subtitle['options']['resources'],['subtitles'])
        self.assertFalse(any(p['instanceId']=='aiometadata-local' for p in config['presets']))


    def test_usenet_uses_native_nzb_route_and_skips_torrent_sources_without_debrid(self):
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', ''), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'TORBOX_API_KEY', ''), \
             patch.object(bootstrap, 'ALLDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'DEBRIDLINK_API_KEY', ''), \
             patch.object(bootstrap, 'EASYNEWS_USER', ''), \
             patch.object(bootstrap, 'EASYNEWS_PASSWORD', ''), \
             patch.dict(bootstrap.os.environ, {
                 'USENET_ENABLED': 'true',
                 'USENET_HOST': 'news.fixture',
                 'USENET_USER_B64': 'Zml4dHVyZQ==',
                 'USENET_PASS_B64': 'Zml4dHVyZQ==',
                 'PREMIUMIZE_API_KEY': '',
                 'REALDEBRID_API_KEY': '',
                 'TORBOX_API_KEY': '',
                 'ALLDEBRID_API_KEY': '',
                 'DEBRIDLINK_API_KEY': '',
                 'EASYNEWS_USER': '',
                 'EASYNEWS_PASSWORD': '',
             }):
            config = bootstrap.build_default_config(probe_services=False)
        self.assertTrue(any(s['id']=='aiostreams' for s in config['services']))
        self.assertFalse(any(s['id']=='nzbdav' for s in config['services']))
        self.assertFalse(any(s['id']=='infinidysk' for s in config['services']))
        preset=next(p for p in config['presets'] if p['instanceId']=='prowlarr-usenet')
        self.assertEqual(preset['options']['sources'],['usenet']);self.assertEqual(preset['options']['services'],['aiostreams'])
        self.assertFalse(any(p['type']=='comet' for p in config['presets']))
        self.assertFalse(any(p['type']=='torrentio' for p in config['presets']))

    def test_no_metadata_key_does_not_enable_features_that_block_registration(self):
        with patch.object(bootstrap,'TMDB_API_KEY',''),patch.object(bootstrap,'load_env_file'),patch.dict(bootstrap.os.environ,{'TMDB_API_KEY':''}):
            config=bootstrap.build_default_config(probe_services=False)
        self.assertFalse(config['titleMatching']['enabled'])
        self.assertFalse(config['yearMatching']['enabled'])
        self.assertFalse(config['precacheNextEpisode'])
        self.assertFalse(config['failover']['precacheFailover'])
        self.assertEqual(config['failover']['parallel'],2)
        with patch.object(bootstrap,'TMDB_API_KEY','fixture-metadata-key'):
            configured=bootstrap.build_default_config(probe_services=False)
        self.assertTrue(configured['titleMatching']['enabled'])
        self.assertTrue(configured['yearMatching']['enabled'])

    def test_torrentio_uses_one_native_preset_with_explicit_custom_override(self):
        with patch.object(bootstrap,'PREMIUMIZE_API_KEY','fixture-provider-key'),patch.dict(bootstrap.os.environ,{'ENABLE_TORRENTIO':'true','TORRENTIO_URL':''}):
            config=bootstrap.build_default_config(probe_services=False)
        presets=[p for p in config['presets'] if p['type']=='torrentio']
        self.assertEqual(len(presets),1);self.assertTrue(presets[0]['enabled']);self.assertEqual(presets[0]['options']['name'],'Torrentio')
        with patch.object(bootstrap,'PREMIUMIZE_API_KEY','fixture-provider-key'),patch.dict(bootstrap.os.environ,{'ENABLE_TORRENTIO':'false','TORRENTIO_URL':'https://fixture.invalid'}):
            config=bootstrap.build_default_config(probe_services=False)
        preset=next(p for p in config['presets'] if p['type']=='torrentio')
        self.assertFalse(preset['enabled']);self.assertEqual(preset['options']['url'],'https://fixture.invalid')

    def test_public_databases_can_be_toggled(self):
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', 'fixture-provider-key'), patch.dict(bootstrap.os.environ, {'ENABLE_REMUXDB': 'false', 'TORRENTIO_URL': 'https://custom.torrentio.example'}):
            config = bootstrap.build_default_config(probe_services=False)
        self.assertFalse(config['remuxDb']['enabled'])
        preset = next(p for p in config['presets'] if p['type'] == 'torrentio')
        self.assertEqual(preset['options']['url'], 'https://custom.torrentio.example')
        self.assertEqual(preset['options']['name'], 'Torrentio (custom)')

    def test_managed_nzb_indexer_changes_address_in_place_and_can_be_disabled(self):
        existing={'id':73,'implementation':'Newznab','name':'AIO Local Usenet','enable':True,'fields':[{'name':'baseUrl','value':'http://old.fixture'},{'name':'apiKey','value':'fixture-old'}]}
        writes=[]
        def request(url,method='GET',data=None,**kwargs):
            if method=='PUT':writes.append((url,data));return {'id':73}
            return [existing]
        with patch.object(bootstrap,'make_request',side_effect=request),patch.dict(bootstrap.os.environ,{'USENET_ENABLED':'true','NZB_INDEXER_URL':'https://new.fixture','NZB_INDEXER_API_KEY':'fixture-new'}):
            bootstrap.setup_usenet_indexer()
        self.assertEqual(len(writes),1);self.assertTrue(writes[0][0].endswith('/73'))
        self.assertEqual(writes[0][1]['fields'][0]['value'],'https://new.fixture')
        with patch.object(bootstrap,'make_request',side_effect=request),patch.dict(bootstrap.os.environ,{'USENET_ENABLED':'false'}):
            bootstrap.setup_usenet_indexer()
        self.assertFalse(writes[-1][1]['enable'])

    def test_configuration_writes_supply_the_explicit_access_key(self):
        with patch.object(bootstrap,'ADDON_PASSWORD','fixture-config-access'):
            config=bootstrap.build_default_config(probe_services=False)
        self.assertEqual(config['accessKey'],'fixture-config-access')

    def test_unreachable_custom_addons_omitted_from_presets_in_core_profile(self):
        # In core profile, optional services (e.g. Anime Kitsu) may not be running.
        # Ensure build_default_config omits unreachable custom addons so AIOStreams
        # doesn't reject the profile with USER_INVALID_CONFIG.
        def mock_reachable(url, timeout=1.0):
            return "aiometadata" in url

        with patch.object(bootstrap, "is_url_reachable", side_effect=mock_reachable):
            config = bootstrap.build_default_config(aiometadata_manifest="http://aiometadata:4005/stremio/test/manifest.json")
            presets = config.get("presets", [])
            preset_ids = [p.get("instanceId") for p in presets]
            # Reachable ones kept
            self.assertIn("aiometadata-local", preset_ids)
            # Unreachable custom addons omitted
            self.assertNotIn("debrid-search-local", preset_ids)
            self.assertNotIn("anime-kitsu-local", preset_ids)
            self.assertNotIn("comet-local", preset_ids)

    def test_builtin_proxy_is_disabled_for_local_base_url(self):
        with patch.object(bootstrap, "BASE_URL", "http://localhost:3001"):
            config = bootstrap.build_default_config()
        self.assertFalse(config["proxy"]["enabled"])

    def test_builtin_proxy_is_enabled_for_public_base_url(self):
        with patch.object(bootstrap, "BASE_URL", "https://aio.example.test"):
            config = bootstrap.build_default_config()
        self.assertTrue(config["proxy"]["enabled"])
        self.assertEqual(config["proxy"].get("proxiedServices"), ["realdebrid", "premiumize", "alldebrid", "torbox", "debridlink", "easynews", "aiostreams", "none"])
        self.assertNotIn("nzbdav", config["proxy"].get("proxiedServices"))
        self.assertNotIn("infinidysk", config["proxy"].get("proxiedServices"))

    def test_stremthru_store_preset_configured_with_debrid(self):
        with patch.object(bootstrap, "PREMIUMIZE_API_KEY", "mock-prem-key"):
            config = bootstrap.build_default_config(probe_services=False)
            store_preset = next((p for p in config.get("presets", []) if p["type"] == "stremthruStore"), None)
            self.assertIsNotNone(store_preset)
            self.assertTrue(store_preset["enabled"])
            self.assertEqual(store_preset["instanceId"], "stremthru-store-local")
            self.assertIn("catalog", store_preset["options"]["resources"])

    def test_optional_tvdb_key_does_not_block_aiostreams_config(self):
        with patch.object(bootstrap, "TVDB_API_KEY", "optional-tvdb-key"):
            config = bootstrap.build_default_config()
        self.assertNotEqual(config.get("tvdbApiKey"), "optional-tvdb-key")

    def test_anime_and_usenet_presets_present_in_default_config(self):
        with patch.object(bootstrap, "EASYNEWS_USER", ""), patch.object(bootstrap, "EASYNEWS_PASSWORD", ""):
            config = bootstrap.build_default_config(probe_services=False)
            presets = {p["instanceId"]: p for p in config.get("presets", [])}
            self.assertIn("anime-tosho-new", presets)
            self.assertFalse(presets["anime-tosho-new"]["enabled"])
            self.assertIn("tsukihime-scraper", presets)
            self.assertFalse(presets["tsukihime-scraper"]["enabled"])
            self.assertIn("neko-bt-scraper", presets)
            self.assertFalse(presets["neko-bt-scraper"]["enabled"])
            self.assertIn("easynews-search", presets)
            self.assertFalse(presets["easynews-search"]["enabled"])

    def test_easynews_configuration_activates_service_and_preset(self):
        with patch.object(bootstrap, "EASYNEWS_USER", "mockuser"), patch.object(bootstrap, "EASYNEWS_PASSWORD", "mockpass"):
            config = bootstrap.build_default_config(probe_services=False)
            easynews_service = next((s for s in config.get("services", []) if s["id"] == "easynews"), None)
            self.assertIsNotNone(easynews_service)
            self.assertEqual(easynews_service["credentials"]["username"], "mockuser")
            self.assertEqual(easynews_service["credentials"]["password"], "mockpass")
            easynews_preset = next((p for p in config.get("presets", []) if p["type"] == "easynews-search"), None)
            self.assertIsNotNone(easynews_preset)
            self.assertTrue(easynews_preset["enabled"])

    def test_resolve_aiometadata_template_path(self):
        path_anime = bootstrap.resolve_aiometadata_template_path("with-anime")
        self.assertTrue(path_anime.endswith("tamtaro-aiometadata-with-anime.json"))
        path_no_anime = bootstrap.resolve_aiometadata_template_path("without-anime")
        self.assertTrue(path_no_anime.endswith("tamtaro-aiometadata-without-anime.json"))
        path_grabber = bootstrap.resolve_aiometadata_template_path("grabberhawk")
        self.assertTrue(path_grabber.endswith("grabberhawk-aiometadata-config.json"))

    def test_seadex_enabled_in_default_config(self):
        config = bootstrap.build_default_config(probe_services=False)
        self.assertTrue(config.get("enableSeadex"))
    def test_native_anime_sources_are_not_seeded_again_in_prowlarr(self):
        self.assertNotIn("subsplease", bootstrap.TARGET_INDEXERS)
        self.assertNotIn("animetosho-xyz", bootstrap.TARGET_INDEXERS)

    def test_native_anime_sources_are_scoped_and_require_compatible_accounts(self):
        with patch.object(bootstrap,'PREMIUMIZE_API_KEY','fixture-provider-key'),patch.dict(bootstrap.os.environ,{'ENABLE_ANIME_SOURCES':'true','USENET_ENABLED':'false'}):
            config=bootstrap.build_default_config(probe_services=False)
        sources=[p for p in config['presets'] if p['type'] in ('anime-tosho-new','neko-bt','tsukihime')]
        self.assertEqual(len(sources),3)
        for source in sources:
            self.assertTrue(source['enabled']);self.assertEqual(source['options']['mediaTypes'],['anime'])
            self.assertEqual(source['options']['services'],['premiumize']);self.assertFalse(source['options']['useMultipleInstances'])
        with patch.object(bootstrap,'PREMIUMIZE_API_KEY',''),patch.dict(bootstrap.os.environ,{'ENABLE_ANIME_SOURCES':'true','USENET_ENABLED':'true','USENET_HOST':'news.fixture','USENET_USER_B64':'Zml4dHVyZQ==','USENET_PASS_B64':'Zml4dHVyZQ=='}):
            config=bootstrap.build_default_config(probe_services=False)
        sources={p['type']:p for p in config['presets'] if p['type'] in ('anime-tosho-new','neko-bt','tsukihime')}
        self.assertFalse(sources['anime-tosho-new']['enabled']);self.assertFalse(sources['neko-bt']['enabled'])
        self.assertFalse(sources['tsukihime']['enabled']);self.assertEqual(sources['tsukihime']['options']['services'],[])

    def test_anime_sources_auto_enabled_via_template_and_env(self):
        # 1. Auto-enable when AIOMETADATA_TEMPLATE contains 'anime'
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', 'fixture-provider-key'), \
             patch.dict(bootstrap.os.environ, {'ENABLE_ANIME_SOURCES': 'false', 'AIOMETADATA_TEMPLATE': 'tamtaro-aiometadata-with-anime.json'}):
            config = bootstrap.build_default_config(probe_services=False)
        sources = [p for p in config['presets'] if p['type'] in ('anime-tosho-new', 'neko-bt', 'tsukihime')]
        for s in sources:
            self.assertTrue(s['enabled'])

        # 2. Auto-enable when active template is an anime variant
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', 'fixture-provider-key'), \
             patch.dict(bootstrap.os.environ, {'ENABLE_ANIME_SOURCES': 'false', 'AIOMETADATA_TEMPLATE': ''}):
            template_path = bootstrap.resolve_path("templates/setup-templates/tamtaro-anime-only.json", "/templates/setup-templates/tamtaro-anime-only.json")
            with open(template_path, "r", encoding="utf-8") as f:
                tmpl_data = json.load(f)
            config = bootstrap.build_default_config(probe_services=False, base_config=tmpl_data.get("config"))
        sources = [p for p in config['presets'] if p['type'] in ('anime-tosho-new', 'neko-bt', 'tsukihime')]
        for s in sources:
            self.assertTrue(s['enabled'])

    def test_anime_only_template_includes_prowlarr_and_knaben(self):
        template_path = bootstrap.resolve_path("templates/setup-templates/tamtaro-anime-only.json", "/templates/setup-templates/tamtaro-anime-only.json")
        with open(template_path, "r", encoding="utf-8") as f:
            tmpl_data = json.load(f)
        presets = tmpl_data.get("config", {}).get("presets", [])
        types = [p.get("type") for p in presets]
        self.assertIn("prowlarr", types)
        self.assertIn("knaben", types)
        prowlarr_preset = next(p for p in presets if p.get("type") == "prowlarr")
        self.assertEqual(prowlarr_preset.get("instanceId"), "prowlarr-scraper")
        self.assertTrue(prowlarr_preset.get("enabled"))
        knaben_preset = next(p for p in presets if p.get("type") == "knaben")
        self.assertEqual(knaben_preset.get("instanceId"), "knaben-scraper")
        self.assertTrue(knaben_preset.get("enabled"))
        self.assertEqual(knaben_preset.get("options", {}).get("mediaTypes"), ["anime"])

    def test_easynews_has_one_direct_owner_and_does_not_enable_torrent_routes(self):
        with patch.object(bootstrap,'PREMIUMIZE_API_KEY',''),patch.object(bootstrap,'EASYNEWS_USER','fixture-easynews-user'),patch.object(bootstrap,'EASYNEWS_PASSWORD','fixture-easynews-pass'):
            config=bootstrap.build_default_config(probe_services=False)
        enabled=[p for p in config['presets'] if p.get('enabled')]
        self.assertFalse(any(p['type'] in ('comet','torrentio') for p in enabled))
        route=next(p for p in enabled if p['type']=='easynews-search')
        self.assertEqual(route['options']['services'],['easynews'])
        self.assertFalse(route['options']['paginate'])

    def test_usenet_only_mode_configuration(self):
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', ''), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'TORBOX_API_KEY', ''), \
             patch.object(bootstrap, 'ALLDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'DEBRIDLINK_API_KEY', ''), \
             patch.object(bootstrap, 'EASYNEWS_USER', ''), \
             patch.object(bootstrap, 'EASYNEWS_PASSWORD', ''), \
             patch.dict(bootstrap.os.environ, {
                 'USENET_ENABLED': 'true',
                 'USENET_HOST': 'news.fixture',
                 'USENET_USER_B64': 'Zml4dHVyZQ==',
                 'USENET_PASS_B64': 'Zml4dHVyZQ==',
                 'STREAMING_MODE': 'usenet',
                 'BASE_URL': 'https://aio.example.com',
                 'PREMIUMIZE_API_KEY': '',
                 'REALDEBRID_API_KEY': '',
                 'TORBOX_API_KEY': '',
                 'ALLDEBRID_API_KEY': '',
                 'DEBRIDLINK_API_KEY': '',
                 'EASYNEWS_USER': '',
                 'EASYNEWS_PASSWORD': '',
             }):
            config = bootstrap.build_default_config(probe_services=False)
        self.assertTrue(any(s['id'] == 'aiostreams' for s in config['services']))
        self.assertFalse(any(s['id'] == 'nzbdav' for s in config['services']))
        self.assertFalse(any(s['id'] == 'infinidysk' for s in config['services']))
        self.assertIn('aiostreams', config['proxy']['proxiedServices'])
        self.assertNotIn('nzbdav', config['proxy']['proxiedServices'])
        self.assertNotIn('infinidysk', config['proxy']['proxiedServices'])
        self.assertEqual(config['cacheAndPlay']['streamTypes'], ['usenet'])
        self.assertEqual(config['failover']['contentTypes'], ['usenet'])
        self.assertFalse(config['failover']['allowCrossType'])
        self.assertFalse(any(p['instanceId'] == 'debrid-search-local' for p in config['presets']))
        self.assertFalse(any(p['instanceId'] == 'comet-local' for p in config['presets']))
        self.assertFalse(any(p['type'] == 'torrentio' for p in config['presets']))
        usenet_p = next(p for p in config['presets'] if p['instanceId'] == 'prowlarr-usenet')
        self.assertTrue(usenet_p['enabled'])
        self.assertEqual(usenet_p['options']['sources'], ['usenet'])
        self.assertEqual(usenet_p['options']['services'], ['aiostreams'])

    def test_prowlarr_scraper_preset_and_knaben_anime(self):
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', 'valid-mock-key'), \
             patch.object(bootstrap, 'is_url_reachable', return_value=True):
            config = bootstrap.build_default_config(probe_services=False)
            prowlarr_p = next((p for p in config.get('presets', []) if p.get('instanceId') == 'prowlarr-scraper'), None)
            self.assertIsNotNone(prowlarr_p)
            self.assertTrue(prowlarr_p['enabled'])
            self.assertEqual(prowlarr_p['options']['sources'], ['torrent'])
            self.assertEqual(prowlarr_p['options']['url'], 'http://prowlarr:9696')

            knaben_p = next((p for p in config.get('presets', []) if p.get('instanceId') == 'knaben-scraper'), None)
            self.assertIsNotNone(knaben_p)
            self.assertTrue(knaben_p['enabled'])
            self.assertEqual(knaben_p['options']['mediaTypes'], ['anime'])
            self.assertEqual(knaben_p['options']['name'], 'Knaben (Anime)')

    def test_bento_anime_preset_with_service_wrap(self):
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', 'valid-mock-key'), \
             patch.object(bootstrap, 'is_url_reachable', return_value=True):
            config = bootstrap.build_default_config(probe_services=False)
            bento = next((p for p in config.get('presets', []) if p.get('instanceId') == 'bento-anime'), None)
            self.assertIsNotNone(bento)
            self.assertTrue(bento['enabled'])
            self.assertEqual(bento['type'], 'custom')
            self.assertFalse(bento['options']['resultPassthrough'])
            self.assertIn('stream', bento['options']['resources'])
            self.assertIn('bento.tweakapps.uk', bento['options']['manifestUrl'])

    def test_bento_preset_requires_debrid_service(self):
        with patch.object(bootstrap, 'PREMIUMIZE_API_KEY', ''), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'TORBOX_API_KEY', ''), \
             patch.object(bootstrap, 'ALLDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'DEBRIDLINK_API_KEY', ''), \
             patch.object(bootstrap, 'EASYDEBRID_API_KEY', ''), \
             patch.object(bootstrap, 'OFFCLOUD_API_KEY', ''), \
             patch.object(bootstrap, 'SEEDR_API_KEY', ''), \
             patch.object(bootstrap, 'is_url_reachable', return_value=True):
            config = bootstrap.build_default_config(probe_services=False)
            bento = next((p for p in config.get('presets', []) if p.get('instanceId') == 'bento-anime'), None)
            self.assertIsNone(bento)

    def test_prowlarr_provisions_anime_trackers_when_schemas_available(self):
        schemas = [
            {"definitionName": "nyaasi", "name": "Nyaa (si)"},
            {"definitionName": "tokyotosho", "name": "Tokyo Toshokan"},
            {"definitionName": "subsplease", "name": "SubsPlease"},
            {"definitionName": "animetosho-xyz", "name": "AnimeTosho"},
            {"definitionName": "anibt", "name": "AniBT"},
            {"definitionName": "anirena", "name": "Anirena"},
            {"definitionName": "bakabt", "name": "BakaBT"},
        ]
        requests = []
        def request(url, method="GET", data=None, headers=None, timeout=12):
            if url.endswith("/api/v1/indexer") and method == "GET":
                return []
            if url.endswith("/api/v1/indexer/schema"):
                return schemas
            if method == "POST":
                requests.append((url, data))
                return {"id": len(requests)}
            return {}

        with patch.object(bootstrap, "make_request", side_effect=request):
            bootstrap.setup_prowlarr_indexers()

        provisioned_defs = [d.get("definitionName") for u, d in requests]
        self.assertIn("nyaasi", provisioned_defs)
        self.assertIn("tokyotosho", provisioned_defs)
        self.assertIn("subsplease", provisioned_defs)
        self.assertIn("animetosho-xyz", provisioned_defs)
        self.assertIn("anibt", provisioned_defs)
        self.assertIn("anirena", provisioned_defs)
        self.assertIn("bakabt", provisioned_defs)

    def test_infinidysk_admin_provisioner_removed(self):
        self.assertFalse(hasattr(bootstrap, "ensure_infinidysk_admin"))

    def test_sync_aiostreams_native_usenet_provisions_providers(self):
        called_endpoints = []
        def mock_request(url, method="GET", headers=None, data=None, timeout=10):
            called_endpoints.append((url, method, data))
            return {"success": True}

        with patch.object(bootstrap, 'is_url_reachable', return_value=True), \
             patch.object(bootstrap, 'get_aiostreams_auth_headers', return_value={"Authorization": "Basic test"}), \
             patch.object(bootstrap, 'make_request', side_effect=mock_request), \
             patch.dict(bootstrap.os.environ, {
                 'USENET_ENABLED': 'true',
                 'USENET_HOST': 'news.example.com',
                 'USENET_USER': 'testuser',
                 'USENET_PASS': 'testpass',
                 'USENET_PORT': '563',
             }):
            res = bootstrap.sync_aiostreams_native_usenet()
            self.assertTrue(res)
            self.assertEqual(len(called_endpoints), 1)
            url, method, data = called_endpoints[0]
            self.assertIn("/api/v1/dashboard/usenet/providers", url)
            self.assertEqual(method, "PUT")
            self.assertEqual(data["providers"][0]["host"], "news.example.com")
            self.assertEqual(data["providers"][0]["username"], "testuser")
            self.assertTrue(data["providers"][0]["tls"])

    def test_sync_aiostreams_native_usenet_skips_when_usenet_disabled(self):
        with patch.dict(bootstrap.os.environ, {'USENET_ENABLED': 'false'}):
            self.assertFalse(bootstrap.sync_aiostreams_native_usenet())

    def test_native_usenet_extra_credentials_are_not_trimmed(self):
        with patch.dict(os.environ, {
            'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture.invalid',
            'USENET_USER': 'primary', 'USENET_PASS': 'primary-pass',
            'USENET_USER_B64': '', 'USENET_PASS_B64': '', 'USENET_EXTRA_SERVERS_B64': '',
            'USENET_EXTRA_SERVERS': json.dumps([{'host': 'backup.fixture.invalid',
                'username': ' secondary ', 'password': ' secret ', 'backupOnly': True}])
        }, clear=True), patch.object(bootstrap, 'get_aiostreams_auth_headers', return_value={}), \
             patch.object(bootstrap, 'make_request', return_value={'success': True}) as request:
            self.assertTrue(bootstrap.sync_aiostreams_native_usenet())
            secondary = request.call_args.kwargs['data']['providers'][1]
            self.assertEqual(secondary['username'], ' secondary ')
            self.assertEqual(secondary['password'], ' secret ')
            self.assertTrue(secondary['isBackup'])

    def test_newznab_paths_do_not_overwrite_each_other_and_reapply_is_idempotent(self):
        with patch.dict(os.environ, {
            'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture.invalid',
            'USENET_USER': 'user', 'USENET_PASS': 'pass',
            'NZB_INDEXER_URL': 'https://index.fixture.invalid/first', 'NZB_INDEXER_API_KEY': 'first-key',
            'USENET_EXTRA_INDEXERS': json.dumps([
                {'url': 'https://index.fixture.invalid/second', 'apiKey': 'second-key'},
                {'url': 'https://INDEX.fixture.invalid:443/first/api/', 'apiKey': 'first-key'}])
        }, clear=True):
            first = bootstrap.build_default_config(base_config={}, probe_services=False)
            second = bootstrap.build_default_config(base_config=first, probe_services=False)
        self.assertEqual({p['instanceId'] for p in first['presets'] if p['type'] == 'newznab'},
                         {p['instanceId'] for p in second['presets'] if p['type'] == 'newznab'})
        for config in (first, second):
            presets = [p for p in config['presets'] if p['type'] == 'newznab']
            self.assertEqual(len(presets), 2)
            self.assertEqual(len({p['instanceId'] for p in presets}), 2)
            self.assertEqual({p['options']['api']['url']: p['options']['api']['apiKey'] for p in presets}, {
                'https://index.fixture.invalid/first/api': 'first-key',
                'https://index.fixture.invalid/second/api': 'second-key'})

    def test_managed_newznab_endpoint_edits_replace_old_paths_and_preserve_custom(self):
        custom = {'type': 'newznab', 'instanceId': 'my-custom-indexer', 'enabled': False,
                  'options': {'name': 'My custom indexer', 'api': {'url': 'https://custom.fixture.invalid/api', 'apiKey': 'custom-fixture'},
                              'timeout': 16000, 'services': ['custom-service'], 'resources': ['stream']}}
        custom_expected = json.loads(json.dumps(custom))
        with patch.dict(os.environ, {
            'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture.invalid',
            'USENET_USER': 'user', 'USENET_PASS': 'pass',
            'NZB_INDEXER_URL': 'https://index.fixture.invalid/first', 'NZB_INDEXER_API_KEY': 'primary-fixture',
            'USENET_EXTRA_INDEXERS': json.dumps([{'id': 'stable-extra-row', 'url': 'https://index.fixture.invalid/second', 'apiKey': 'extra-fixture'}])
        }, clear=True):
            first = bootstrap.build_default_config(base_config={'presets': [custom]}, probe_services=False)
            initial_ids = {p['instanceId'] for p in first['presets'] if p['type'] == 'newznab'}
            os.environ['NZB_INDEXER_URL'] = 'https://index.fixture.invalid/primary-changed'
            os.environ['USENET_EXTRA_INDEXERS'] = json.dumps([{'id': 'stable-extra-row', 'url': 'https://index.fixture.invalid/extra-changed', 'apiKey': 'extra-fixture'}])
            second = bootstrap.build_default_config(base_config=first, probe_services=False)
        presets = [p for p in second['presets'] if p['type'] == 'newznab']
        self.assertEqual({p['instanceId'] for p in presets}, initial_ids)
        self.assertEqual(len(presets), 3)
        self.assertEqual(next(p for p in presets if p['instanceId'] == 'my-custom-indexer'), custom_expected)
        self.assertEqual({p['options']['api']['url'] for p in presets}, {
            'https://index.fixture.invalid/primary-changed/api',
            'https://index.fixture.invalid/extra-changed/api',
            'https://custom.fixture.invalid/api'})

    def test_removed_managed_indexer_does_not_duplicate_changed_primary_endpoint(self):
        with patch.dict(os.environ, {
            'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture.invalid',
            'USENET_USER': 'user', 'USENET_PASS': 'pass',
            'NZB_INDEXER_URL': 'https://a.fixture.invalid', 'NZB_INDEXER_API_KEY': 'primary-fixture',
            'USENET_EXTRA_INDEXERS': json.dumps([{'id': 'extra-b', 'url': 'https://b.fixture.invalid', 'apiKey': 'extra-fixture'}])
        }, clear=True):
            first = bootstrap.build_default_config(base_config={}, probe_services=False)
            old_extra = next(p['instanceId'] for p in first['presets']
                             if p['type'] == 'newznab' and p['instanceId'] != 'newznab-managed-primary')
            first['groups'] = {'enabled': True, 'groupings': [
                {'name': 'Usenet', 'addons': ['newznab-managed-primary', old_extra]}]}
            os.environ['NZB_INDEXER_URL'] = 'https://b.fixture.invalid'
            os.environ['USENET_EXTRA_INDEXERS'] = '[]'
            second = bootstrap.build_default_config(base_config=first, probe_services=False)
        presets = [p for p in second['presets'] if p['type'] == 'newznab']
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0]['instanceId'], 'newznab-managed-primary')
        self.assertEqual(presets[0]['options']['api']['url'], 'https://b.fixture.invalid/api')
        self.assertEqual(second['groups']['groupings'][0]['addons'], ['newznab-managed-primary'])

    def test_removing_all_saved_indexers_preserves_custom_and_legacy_presets(self):
        custom = {'type': 'newznab', 'instanceId': 'my-custom-indexer', 'enabled': False,
                  'options': {'api': {'url': 'https://custom.fixture.invalid/api', 'apiKey': 'custom-fixture'},
                              'timeout': 16000, 'services': ['custom-service']}}
        legacy = {'type': 'newznab', 'instanceId': 'newznab-legacy', 'enabled': True,
                  'options': {'api': {'url': 'https://legacy.fixture.invalid/api', 'apiKey': 'legacy-fixture'}}}
        expected = json.loads(json.dumps([custom, legacy]))
        with patch.dict(os.environ, {
            'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture.invalid',
            'USENET_USER': 'user', 'USENET_PASS': 'pass',
            'NZB_INDEXER_URL': 'https://a.fixture.invalid', 'NZB_INDEXER_API_KEY': 'primary-fixture',
            'USENET_EXTRA_INDEXERS': json.dumps([{'id': 'extra-b', 'url': 'https://b.fixture.invalid', 'apiKey': 'extra-fixture'}])
        }, clear=True):
            first = bootstrap.build_default_config(base_config={'presets': [custom, legacy]}, probe_services=False)
            os.environ['NZB_INDEXER_URL'] = ''
            os.environ['NZB_INDEXER_API_KEY'] = ''
            os.environ['USENET_EXTRA_INDEXERS'] = '[]'
            second = bootstrap.build_default_config(base_config=first, probe_services=False)
        self.assertEqual([p for p in second['presets'] if p['type'] == 'newznab'], expected)

    def test_legacy_newznab_endpoint_is_adopted_without_losing_group_reference(self):
        legacy = {'type': 'newznab', 'instanceId': 'newznab-index', 'enabled': True,
                  'options': {'api': {'url': 'https://INDEX.fixture.invalid:443/api/', 'apiKey': 'old-fixture'}}}
        with patch.dict(os.environ, {
            'USENET_ENABLED': 'true', 'USENET_HOST': 'news.fixture.invalid',
            'USENET_USER': 'user', 'USENET_PASS': 'pass',
            'NZB_INDEXER_URL': 'https://index.fixture.invalid', 'NZB_INDEXER_API_KEY': 'new-fixture'
        }, clear=True):
            result = bootstrap.build_default_config(base_config={'presets': [legacy],
                'groups': {'enabled': True, 'groupings': [{'name': 'Usenet', 'addons': ['newznab-index']}]}}, probe_services=False)
        presets = [p for p in result['presets'] if p['type'] == 'newznab']
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0]['instanceId'], 'newznab-managed-primary')
        self.assertEqual(presets[0]['options']['api']['apiKey'], 'new-fixture')
        self.assertEqual(result['groups']['groupings'][0]['addons'], ['newznab-managed-primary'])

    def test_jikan_api_base_resolution(self):
        # Default should return Tenrai
        self.assertEqual(bootstrap.resolve_jikan_api_base("", probe_services=False), "https://api.tenrai.org/v4")
        # Explicit custom URL should be respected
        self.assertEqual(bootstrap.resolve_jikan_api_base("https://custom.jikan.moe/v4", probe_services=False), "https://custom.jikan.moe/v4")
        # When local jikan is reachable, seamlessly select it
        with patch.object(bootstrap, "is_url_reachable", side_effect=lambda url, timeout=1.0: "jikan-api" in url):
            self.assertEqual(bootstrap.resolve_jikan_api_base("", probe_services=True), "http://jikan-api:8080/v4")

    def test_bitmagnet_prowlarr_registration_when_reachable(self):
        schemas = [
            {"definitionName": "Torznab", "implementation": "Torznab", "name": "Torznab", "fields": [
                {"name": "baseUrl", "value": ""},
                {"name": "apiPath", "value": ""},
                {"name": "apiKey", "value": ""},
            ]}
        ]
        requests = []
        def request(url, method="GET", data=None, headers=None, timeout=12):
            if url.endswith("/api/v1/indexer") and method == "GET":
                return []
            if url.endswith("/api/v1/indexer/schema"):
                return schemas
            if method == "POST":
                requests.append((url, data))
                return {"id": 10}
            return {}

        with patch.object(bootstrap, "make_request", side_effect=request), \
             patch.object(bootstrap, "is_url_reachable", side_effect=lambda url, timeout=1.0: "bitmagnet" in url):
            bootstrap.setup_prowlarr_indexers()

        bitmagnet_req = next((d for u, d in requests if d.get("name") == "Bitmagnet (Torznab Local)"), None)
        self.assertIsNotNone(bitmagnet_req)
        # Direct Torznab preset in AIOStreams queries Bitmagnet directly; Prowlarr indexer is kept disabled to prevent 2x duplicate load
        self.assertFalse(bitmagnet_req["enable"])
        fields = {f["name"]: f["value"] for f in bitmagnet_req["fields"]}
        self.assertEqual(fields["baseUrl"], "http://bitmagnet:3333/torznab")

    def test_bitmagnet_aiostreams_preset_when_configured(self):
        with patch.dict(os.environ, {"BITMAGNET_URL": "http://bitmagnet:3333"}), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', 'rd_test'), \
             patch.object(bootstrap, "is_url_reachable", side_effect=lambda url, timeout=1.0: "bitmagnet" in url or "aiostreams" in url):
            config = bootstrap.build_default_config(probe_services=True)
            preset = next((p for p in config.get("presets", []) if p.get("instanceId") == "bitmagnet-local"), None)
            self.assertIsNotNone(preset)
            self.assertEqual(preset["type"], "torznab")
            self.assertTrue(preset["enabled"])
            self.assertEqual(preset["options"]["url"], "http://bitmagnet:3333/torznab")
            self.assertEqual(preset["options"]["api"]["url"], "http://bitmagnet:3333/torznab")

    def test_bitmagnet_aiostreams_preset_omitted_when_unreachable(self):
        base = {
            "presets": [
                {"type": "torznab", "instanceId": "bitmagnet-local", "options": {"url": "http://bitmagnet:3333/torznab"}}
            ]
        }
        with patch.dict(os.environ, {"BITMAGNET_URL": "http://bitmagnet:3333"}), \
             patch.object(bootstrap, 'REALDEBRID_API_KEY', 'rd_test'), \
             patch.object(bootstrap, "is_url_reachable", return_value=False):
            config = bootstrap.build_default_config(probe_services=True, base_config=base)
            preset = next((p for p in config.get("presets", []) if p.get("instanceId") == "bitmagnet-local"), None)
            self.assertIsNone(preset)

    def test_deprecated_presets_removal(self):
        base = {
            "presets": [
                {"type": "comet", "instanceId": "comet-preset", "options": {}},
                {"type": "sootio", "instanceId": "sootio-preset", "options": {}},
                {"type": "nuvio", "instanceId": "nuvio-preset", "options": {}},
                {"type": "custom", "instanceId": "mediaflow-custom", "options": {"name": "MediaFlow"}},
                {"type": "custom", "instanceId": "slicksync-custom", "options": {"name": "SlickSync"}},
                {"type": "custom", "instanceId": "stremio-web-custom", "options": {"url": "http://stremio-web:8080"}},
                {"type": "custom", "instanceId": "custom-debrid-search", "options": {"name": "DS"}},
                {"type": "custom", "instanceId": "clean-custom-1", "options": {"url": "http://comet:8000"}},
                {"type": "custom", "instanceId": "clean-custom-2", "options": {"manifestUrl": "http://sootio:55771/manifest.json"}},
                {"type": "custom", "instanceId": "clean-custom-3", "options": {"url": "http://debrid-search:5000/api"}},
                {"type": "prowlarr", "instanceId": "prowlarr-scraper", "options": {"sources": ["torrent"]}},
            ]
        }
        with patch.object(bootstrap, "PREMIUMIZE_API_KEY", "key"):
            config = bootstrap.build_default_config(probe_services=False, base_config=base)

        preset_ids = [p.get("instanceId") for p in config["presets"]]
        preset_types = [p.get("type") for p in config["presets"]]
        self.assertNotIn("comet-preset", preset_ids)
        self.assertNotIn("sootio-preset", preset_ids)
        self.assertNotIn("nuvio-preset", preset_ids)
        self.assertNotIn("mediaflow-custom", preset_ids)
        self.assertNotIn("slicksync-custom", preset_ids)
        self.assertNotIn("stremio-web-custom", preset_ids)
        self.assertNotIn("custom-debrid-search", preset_ids)
        self.assertNotIn("clean-custom-1", preset_ids)
        self.assertNotIn("clean-custom-2", preset_ids)
        self.assertNotIn("clean-custom-3", preset_ids)
        self.assertNotIn("comet", preset_types)
        self.assertNotIn("sootio", preset_types)
        self.assertIn("prowlarr-scraper", preset_ids)

    def test_groups_strip_removed_presets_and_disable_when_empty(self):
        base = {
            "presets": [
                {"type": "sootio", "instanceId": "sootio-local", "options": {}},
                {"type": "custom", "instanceId": "comet-local", "options": {"url": "http://comet:8000"}},
            ],
            "groups": {
                "enabled": True,
                "behaviour": "sequential",
                "onConditionFailure": "stop",
                "groupings": [
                    {"addons": ["sootio-local"], "condition": "true"},
                    {"addons": ["comet-local", "debrid-search-scraper"], "condition": "count(cached(totalStreams)) == 0"}
                ]
            }
        }
        config = bootstrap.build_default_config(probe_services=False, base_config=base)
        self.assertIn("groups", config)
        self.assertFalse(config["groups"]["enabled"])
        self.assertEqual(config["groups"]["groupings"], [])

    def test_groups_preserve_valid_addons_and_strip_deprecated(self):
        base = {
            "presets": [
                {"type": "prowlarr", "instanceId": "prowlarr-scraper", "options": {"sources": ["torrent"]}},
                {"type": "sootio", "instanceId": "sootio-local", "options": {}},
            ],
            "groups": {
                "enabled": True,
                "behaviour": "sequential",
                "onConditionFailure": "stop",
                "groupings": [
                    {"addons": ["prowlarr-scraper", "sootio-local"], "condition": "true"},
                    {"addons": ["sootio-local"], "condition": "count(cached(totalStreams)) == 0"}
                ]
            }
        }
        with patch.object(bootstrap, "PREMIUMIZE_API_KEY", "key"):
            config = bootstrap.build_default_config(probe_services=False, base_config=base)

        self.assertTrue(config["groups"]["enabled"])
        self.assertEqual(len(config["groups"]["groupings"]), 1)
        self.assertEqual(config["groups"]["groupings"][0]["addons"], ["prowlarr-scraper"])

    def test_player_preferences_iso_language_normalization(self):
        with tempfile.TemporaryDirectory() as td:
            prefs_file = os.path.join(td, "data", "player_preferences.json")
            os.makedirs(os.path.dirname(prefs_file), exist_ok=True)
            with open(prefs_file, "w", encoding="utf-8") as f:
                json.dump({"audioLanguage": "jpn", "subtitleLanguage": "eng"}, f)
            with patch.dict(os.environ, {"WEB_ROOT": td}):
                config = bootstrap.build_default_config(probe_services=False)
                self.assertEqual(config.get("preferredLanguages"), ["Japanese"])
                self.assertEqual(config.get("preferredSubtitleLanguages"), ["English"])
