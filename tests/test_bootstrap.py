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
    def setUp(self):
        # Unit tests model availability explicitly; DNS/network delays belong in E2E checks.
        probe = patch.object(bootstrap, "is_url_reachable", return_value=True)
        probe.start()
        self.addCleanup(probe.stop)
        requests = patch.object(bootstrap, "make_request", return_value={})
        requests.start()
        self.addCleanup(requests.stop)

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
        with patch.dict(bootstrap.os.environ, {"AIOMETADATA_PROFILE_UUID": "", "SIMKL_CLIENT_ID": "my-simkl-client-id", "ANILIST_TOKEN": "my-anilist-token"}), patch.object(bootstrap, "make_request", return_value=response) as request, patch.object(bootstrap, "update_env_file"):
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
        with patch.dict(bootstrap.os.environ,{"SOOTIO_MODE":"off"}),patch.object(bootstrap,"make_request",return_value={}):
            config=bootstrap.build_default_config(probe_services=False)
        subtitle=next(p for p in config['presets'] if p['instanceId']=='subsense-local')
        self.assertNotEqual(subtitle['options']['manifestUrl'],'http://subsense:3100/manifest.json')
        self.assertEqual(subtitle['options']['resources'],['subtitles'])
        self.assertFalse(any(p['instanceId']=='aiometadata-local' for p in config['presets']))

    def test_sootio_is_sequential_fallback_not_parallel_default(self):
        with patch.dict(bootstrap.os.environ,{"SOOTIO_MODE":"fallback"}), patch.object(bootstrap,'PREMIUMIZE_API_KEY','fixture-provider-key'):
            config=bootstrap.build_default_config(probe_services=False)
        self.assertEqual(config['groups']['behaviour'],'sequential')
        self.assertEqual(config['groups']['groupings'][1]['addons'],['sootio-local'])
        self.assertEqual(config['groups']['groupings'][1]['condition'],'count(cached(totalStreams)) == 0')
        anime=next(p for p in config['presets'] if p['instanceId']=='anime-kitsu-local')
        self.assertEqual(anime['options']['resources'],['catalog','meta'])


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
        self.assertTrue(any(s['id']=='nzbdav' for s in config['services']))
        preset=next(p for p in config['presets'] if p['instanceId']=='prowlarr-usenet')
        self.assertEqual(preset['options']['sources'],['usenet']);self.assertEqual(preset['options']['services'],['nzbdav'])
        self.assertFalse(any(p['type']=='comet' or p['instanceId']=='sootio-local' for p in config['presets']))
        self.assertFalse(any(p['type']=='torrentio' for p in config['presets']))

    def test_no_metadata_key_does_not_enable_features_that_block_registration(self):
        with patch.object(bootstrap,'TMDB_API_KEY',''),patch.object(bootstrap,'load_env_file'),patch.dict(bootstrap.os.environ,{'TMDB_API_KEY':''}):
            config=bootstrap.build_default_config(probe_services=False)
        self.assertFalse(config['titleMatching']['enabled'])
        self.assertFalse(config['yearMatching']['enabled'])
        self.assertFalse(config['precacheNextEpisode'])
        self.assertFalse(config['failover']['precacheFailover'])
        self.assertEqual(config['failover']['parallel'],1)
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
        # In core profile, debrid-search, sootio, etc. are not running.
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
            self.assertNotIn("sootio-local", preset_ids)
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
        self.assertEqual(config["proxy"].get("proxiedServices"), ["realdebrid", "premiumize", "alldebrid", "torbox", "debridlink", "easynews", "nzbdav", "none"])

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
        self.assertTrue(sources['tsukihime']['enabled']);self.assertEqual(sources['tsukihime']['options']['services'],['nzbdav'])

    def test_easynews_has_one_direct_owner_and_does_not_enable_torrent_routes(self):
        with patch.object(bootstrap,'PREMIUMIZE_API_KEY',''),patch.object(bootstrap,'EASYNEWS_USER','fixture-easynews-user'),patch.object(bootstrap,'EASYNEWS_PASSWORD','fixture-easynews-pass'):
            config=bootstrap.build_default_config(probe_services=False)
        enabled=[p for p in config['presets'] if p.get('enabled')]
        self.assertFalse(any(p['type'] in ('comet','torrentio') or p['instanceId']=='sootio-local' for p in enabled))
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
        self.assertTrue(any(s['id'] == 'nzbdav' for s in config['services']))
        self.assertIn('nzbdav', config['proxy']['proxiedServices'])
        self.assertEqual(config['cacheAndPlay']['streamTypes'], ['usenet'])
        self.assertEqual(config['failover']['contentTypes'], ['usenet'])
        self.assertFalse(config['failover']['allowCrossType'])
        self.assertFalse(any(p['instanceId'] == 'debrid-search-local' for p in config['presets']))
        self.assertFalse(any(p['instanceId'] == 'comet-local' for p in config['presets']))
        self.assertFalse(any(p['instanceId'] == 'sootio-local' for p in config['presets']))
        self.assertFalse(any(p['type'] == 'torrentio' for p in config['presets']))
        usenet_p = next(p for p in config['presets'] if p['instanceId'] == 'prowlarr-usenet')
        self.assertTrue(usenet_p['enabled'])
        self.assertEqual(usenet_p['options']['sources'], ['usenet'])
        self.assertEqual(usenet_p['options']['services'], ['nzbdav'])
