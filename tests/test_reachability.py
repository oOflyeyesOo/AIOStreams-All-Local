"""Tests for stack/Cloudflare reachability checks and Compose port-mapping consistency."""

import os
from pathlib import Path
import re
import socket
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import yaml

from init.service_inventory import INTEGRATIONS, SERVICE_PORT_MAP
from tests import check_stack
from tools import reachability


ROOT = Path(__file__).resolve().parents[1]


def _extract_host_container_ports(port_spec: str) -> tuple[int, int]:
    """Extract (default_host_port, container_port) from a Compose port mapping string."""
    clean = str(port_spec).strip().strip("\"'")
    # Remove optional ${INTERNAL_BIND_IP:-127.0.0.1}: prefix
    if clean.startswith("${INTERNAL_BIND_IP"):
        _, clean = clean.split(":", 1)
    elif clean.startswith("127.0.0.1:"):
        _, clean = clean.split(":", 1)

    host_part, container_part = clean.rsplit(":", 1)
    container_port = int(re.findall(r"(\d+)", container_part)[-1])
    host_nums = re.findall(r":-(\d+)", host_part) or re.findall(r"(\d+)", host_part)
    host_port = int(host_nums[-1])
    return host_port, container_port


class TestComposePortConsistency(unittest.TestCase):

    def setUp(self):
        self.compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        self.manager = yaml.safe_load((ROOT / "compose.manager.yml").read_text(encoding="utf-8"))
        self.aio = yaml.safe_load((ROOT / "docker-compose.aio.yml").read_text(encoding="utf-8"))

    def test_force_proxy_url_and_base_url_default_to_3001(self):
        for label, doc in (("docker-compose.yml", self.compose), ("compose.manager.yml", self.manager)):
            aio_env = doc["services"]["aiostreams"]["environment"]
            env_map = dict(item.split("=", 1) for item in aio_env if isinstance(item, str) and "=" in item)
            self.assertIn(":3001", env_map["BASE_URL"], f"{label} BASE_URL must default to 3001")
            self.assertIn(":3001", env_map["FORCE_PROXY_URL"], f"{label} FORCE_PROXY_URL must default to 3001")
            self.assertNotIn(":3000", env_map["FORCE_PROXY_URL"], f"{label} FORCE_PROXY_URL must not default to 3000")

    def test_compose_manager_and_aio_ports_match_service_inventory(self):
        services = self.compose["services"]
        mgr_services = self.manager["services"]

        for svc, (internal_port, default_host_port, _) in SERVICE_PORT_MAP.items():
            if svc == "stremio-subsense" or svc == "lumiere-db":
                continue
            self.assertIn(svc, services)
            self.assertIn(svc, mgr_services)
            h_port, c_port = _extract_host_container_ports(services[svc]["ports"][0])
            self.assertEqual((h_port, c_port), (default_host_port, internal_port), f"Mismatch in docker-compose.yml for {svc}")
            mh_port, mc_port = _extract_host_container_ports(mgr_services[svc]["ports"][0])
            self.assertEqual((mh_port, mc_port), (default_host_port, internal_port), f"Mismatch in compose.manager.yml for {svc}")

        # Portal host/container port
        self.assertEqual(_extract_host_container_ports(services["portal"]["ports"][0]), (8088, 8088))
        self.assertEqual(_extract_host_container_ports(mgr_services["portal"]["ports"][0]), (8088, 8088))

        # AIO DinD outer ports must publish 8088, 3001, 4005, etc.
        aio_ports = {_extract_host_container_ports(p) for p in self.aio["services"]["aio-stack"]["ports"]}
        self.assertIn((8088, 8088), aio_ports)
        self.assertIn((3001, 3001), aio_ports)
        self.assertIn((4005, 4005), aio_ports)
        for _, host_port, _ in (
            SERVICE_PORT_MAP["prowlarr"],
            SERVICE_PORT_MAP["zilean"],
            SERVICE_PORT_MAP["stremthru"],
            SERVICE_PORT_MAP["postersplus"],
            SERVICE_PORT_MAP["subsense"],
            SERVICE_PORT_MAP["anime-kitsu"],
            SERVICE_PORT_MAP["jikan-api"],
        ):
            self.assertIn((host_port, host_port), aio_ports)

    def test_all_inventoried_services_have_reachability_specs(self):
        for _, host, _, _ in INTEGRATIONS:
            self.assertIn(host, reachability.SERVICE_REACHABILITY_SPECS)


class TestReachabilityModule(unittest.TestCase):

    def test_active_reachability_services_by_profile(self):
        core = reachability.active_reachability_services({"COMPOSE_PROFILES": "core"})
        self.assertIn("aiostreams", core)
        self.assertIn("aiometadata", core)
        self.assertIn("lumiere-db", core)
        self.assertNotIn("anime-kitsu", core)
        self.assertNotIn("jikan-api", core)

        anime = reachability.active_reachability_services({"COMPOSE_PROFILES": "core,anime"})
        self.assertIn("anime-kitsu", anime)
        self.assertIn("jikan-api", anime)

        all_svcs = reachability.active_reachability_services({"COMPOSE_PROFILES": "all"})
        for _, host, _, _ in INTEGRATIONS:
            self.assertIn(host, all_svcs)
        self.assertIn("jikan-api", all_svcs)

    def test_run_reachability_checks_full_pass_with_external_3001_origin(self):
        mock_containers = {
            "available": True,
            "local_tunnel": {"name": "aio-tunnel", "state": "none", "status": "Not created", "is_local": True, "network_mode": "stremio-net"},
            "external_connectors": [{"id": "ext1", "name": "host-cf", "state": "running", "is_local": False, "is_active": True, "network_mode": "host"}],
            "active_external_connectors": [{"id": "ext1", "name": "host-cf", "state": "running", "is_local": False, "is_active": True, "network_mode": "host"}],
            "has_external": True,
        }

        def fake_probe_http(url, timeout=2.5, follow_redirects=False):
            return True, 200, 1.5, "HTTP 200", None

        with patch("tools.reachability.check_cloudflare_containers", return_value=mock_containers), \
             patch("tools.reachability._in_container", return_value=True), \
             patch("tools.reachability._probe_http", side_effect=fake_probe_http):
            report = reachability.run_reachability_checks(
                env_vars={
                    "COMPOSE_PROFILES": "core",
                    "BASE_URL": "https://watch.example.com",
                    "AIOMETADATA_HOST": "https://aiometa.example.com",
                },
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["recommended_origin"], "http://127.0.0.1:3001")
        self.assertEqual(report["connector_mode"], "external_host")
        self.assertEqual(report["summary"]["failed"], 0)

        ids = {c["id"]: c for c in report["checks"]}
        self.assertTrue(ids["internal:aiostreams"]["ok"])
        self.assertTrue(ids["internal:aiometadata"]["ok"])
        self.assertTrue(ids["host:aiostreams"]["ok"])
        self.assertTrue(ids["host:aiometadata"]["ok"])
        self.assertTrue(ids["host:portal"]["ok"])
        self.assertTrue(ids["portal:/healthz"]["ok"])
        self.assertTrue(ids["portal:/ready"]["ok"])
        self.assertTrue(ids["portal:/watch/"]["ok"])
        self.assertTrue(ids["cloudflare:origin"]["ok"])
        self.assertEqual(ids["cloudflare:origin"]["target"], "http://127.0.0.1:3001")
        self.assertTrue(ids["remote:base_url"]["ok"])
        self.assertTrue(ids["remote:aiometadata"]["ok"])

    def test_detects_unreachable_aiostreams_3000_on_external_connector_and_wrong_host_port(self):
        mock_containers = {
            "available": True,
            "local_tunnel": {"name": "aio-tunnel", "state": "none", "status": "Not created", "is_local": True, "network_mode": "stremio-net"},
            "external_connectors": [{"id": "ext1", "name": "docktun-cf", "state": "running", "is_local": False, "is_active": True, "network_mode": "bridge"}],
            "active_external_connectors": [{"id": "ext1", "name": "docktun-cf", "state": "running", "is_local": False, "is_active": True, "network_mode": "bridge"}],
            "has_external": True,
        }

        with patch("tools.reachability.check_cloudflare_containers", return_value=mock_containers), \
             patch("tools.reachability._probe_http", return_value=(True, 200, 1.0, "HTTP 200", None)):
            # 1. Explicit/saved aiostreams:3000 with external connector -> MUST fail with :3001 remediation
            report = reachability.run_reachability_checks(
                env_vars={"COMPOSE_PROFILES": "core"},
                origin_url="http://aiostreams:3000",
                include_internal=False,
                include_host_ports=False,
                include_portal=False,
                include_remote=False,
            )
            self.assertFalse(report["ok"])
            cf_check = report["checks"][0]
            self.assertEqual(cf_check["status"], "fail")
            self.assertIn("stremio-net", cf_check["detail"])
            self.assertIn("http://host.docker.internal:3001", cf_check["remediation"])

            # 2. Wrong host port 3000 on host.docker.internal -> MUST fail with :3001 remediation
            report_port = reachability.run_reachability_checks(
                env_vars={"COMPOSE_PROFILES": "core"},
                origin_url="http://host.docker.internal:3000",
                include_internal=False,
                include_host_ports=False,
                include_portal=False,
                include_remote=False,
            )
            self.assertFalse(report_port["ok"])
            self.assertIn("port 3000", report_port["checks"][0]["detail"])
            self.assertIn("http://host.docker.internal:3001", report_port["checks"][0]["remediation"])

    def test_allows_aiostreams_3000_when_local_aio_tunnel_is_running(self):
        mock_containers = {
            "available": True,
            "local_tunnel": {"name": "aio-tunnel", "state": "running", "status": "Up 5m", "is_local": True, "network_mode": "stremio-net"},
            "external_connectors": [],
            "active_external_connectors": [],
            "has_external": False,
        }
        with patch("tools.reachability.check_cloudflare_containers", return_value=mock_containers), \
             patch("tools.reachability._probe_http", return_value=(True, 200, 1.2, "HTTP 200", None)):
            report = reachability.run_reachability_checks(
                env_vars={"COMPOSE_PROFILES": "core"},
                include_internal=False,
                include_host_ports=False,
                include_portal=False,
                include_remote=False,
            )
        self.assertTrue(report["ok"])
        self.assertEqual(report["connector_mode"], "local_tunnel")
        self.assertEqual(report["checks"][0]["target"], "http://aiostreams:3000")
        self.assertEqual(report["checks"][0]["status"], "ok")

    def test_remote_base_url_failure_and_internal_dns_outside_container(self):
        dns_err = URLError(socket.gaierror(-2, "Name or service not known"))

        def fake_probe(url, timeout=2.5, follow_redirects=False):
            if "watch.example.com" in url:
                return False, 502, 12.0, "HTTP 502", HTTPError(url, 502, "Bad Gateway", {}, None)
            if "aiostreams:3000" in url:
                return False, None, 1.0, "URLError", dns_err
            return True, 200, 1.0, "HTTP 200", None

        with patch("tools.reachability.check_cloudflare_containers", return_value={"available": False, "external_connectors": [], "has_external": False}), \
             patch("tools.reachability._in_container", return_value=False), \
             patch("tools.reachability._probe_http", side_effect=fake_probe):
            report = reachability.run_reachability_checks(
                env_vars={"COMPOSE_PROFILES": "core", "BASE_URL": "https://watch.example.com"},
                include_host_ports=False,
                include_portal=False,
                include_cloudflare=False,
            )

        ids = {c["id"]: c for c in report["checks"]}
        self.assertEqual(ids["internal:aiostreams"]["status"], "skipped")
        self.assertEqual(ids["remote:base_url"]["status"], "fail")
        self.assertIn("3001", ids["remote:base_url"]["remediation"])


class TestCheckStackModes(unittest.TestCase):

    def test_check_stack_full_mode_checks_internal_host_ports_portal_and_cloudflare_origin(self):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = MagicMock(status=200, read=lambda: b'{"id":"kitsu","resources":["catalog"]}')
        with patch.dict(os.environ, {"COMPOSE_PROFILES": "core", "CLOUDFLARE_ORIGIN_URL": "http://127.0.0.1:3001"}), \
             patch("urllib.request.urlopen", return_value=mock_resp), \
             patch.object(check_stack._NO_REDIRECT_OPENER, "open", return_value=mock_resp), \
             patch("socket.create_connection"):
            results = check_stack.run_stack_checks(mode="full")

        names = {name for name, _, _ in results}
        self.assertIn("aiostreams", names)
        self.assertIn("aiometadata", names)
        self.assertIn("host:aiostreams:3001", names)
        self.assertIn("host:aiometadata:4005", names)
        self.assertIn("host:portal:8088", names)
        self.assertIn("portal:/healthz", names)
        self.assertIn("portal:/ready", names)
        self.assertIn("portal:/watch/", names)
        self.assertIn("cloudflare-origin:http://127.0.0.1:3001", names)
        self.assertTrue(all(passed for _, passed, _ in results), f"Failures: {[r for r in results if not r[1]]}")

    def test_check_stack_flags_aiostreams_3000_from_host(self):
        with patch("os.path.exists", return_value=False):
            name, ok, detail = check_stack.check_cloudflare_origin("http://aiostreams:3000")
        self.assertFalse(ok)
        self.assertIn("3001", detail)


if __name__ == "__main__":
    unittest.main()
