"""
Unit tests for Cloudflare Tunnel & DNS Automation Helper.
"""

import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from tools.cloudflare_helper import (
    parse_tunnel_token,
    check_cloudflare_containers,
    push_cloudflare_dns,
    manage_local_tunnel,
    fetch_cloudflare_tunnel_token,
    recommend_cloudflare_origin,
    validate_service_url,
    build_tunnel_origin_request,
)


class TestCloudflareHelper(unittest.TestCase):

    def test_parse_tunnel_token_valid(self):
        raw = {"a": "account-xyz-123", "t": "tunnel-uuid-456", "s": "secret"}
        token = base64.b64encode(json.dumps(raw).encode()).decode()
        res = parse_tunnel_token(token)
        self.assertTrue(res["valid"])
        self.assertEqual(res["account_id"], "account-xyz-123")
        self.assertEqual(res["tunnel_id"], "tunnel-uuid-456")
        self.assertEqual(res["cname_target"], "tunnel-uuid-456.cfargotunnel.com")
        self.assertTrue(res["is_run_token"])
        self.assertNotIn("token", res)
        self.assertNotIn(token, json.dumps(res))

    def test_tunnel_identifiers_without_secret_are_not_run_tokens(self):
        for data in ({"a": "account", "t": "tunnel"}, {"t": "tunnel", "s": "secret"}):
            with self.subTest(data=data):
                token = base64.b64encode(json.dumps(data).encode()).decode()
                self.assertFalse(parse_tunnel_token(token)["is_run_token"])

    def test_parse_tunnel_token_unpadded(self):
        raw = {"a": "acc", "t": "tun", "s": "sec"}
        token = base64.b64encode(json.dumps(raw).encode()).decode().rstrip("=")
        res = parse_tunnel_token(token)
        self.assertTrue(res["valid"])
        self.assertEqual(res["tunnel_id"], "tun")

    def test_parse_tunnel_token_command_wrapped(self):
        raw = {"a": "acc", "t": "tun-cmd", "s": "sec"}
        b64 = base64.b64encode(json.dumps(raw).encode()).decode()
        cmd = f"cloudflared tunnel run --token {b64}"
        res = parse_tunnel_token(cmd)
        self.assertTrue(res["valid"])
        self.assertEqual(res["tunnel_id"], "tun-cmd")

        # Quoted token or service install command
        cmd2 = f"cloudflared.exe service install \"{b64}\""
        res2 = parse_tunnel_token(cmd2)
        self.assertTrue(res2["valid"])
        self.assertEqual(res2["tunnel_id"], "tun-cmd")

    def test_parse_tunnel_token_raw_uuid(self):
        # 8-4-4-4-12 hex UUID
        uuid_std = "c7b74447-4951-4d37-882f-2d4e73b22cf1"
        res = parse_tunnel_token(uuid_std)
        self.assertTrue(res["valid"])
        self.assertEqual(res["tunnel_id"], uuid_std)
        self.assertEqual(res["cname_target"], f"{uuid_std}.cfargotunnel.com")

        # Uppercase UUID
        res_upper = parse_tunnel_token("C7B74447-4951-4D37-882F-2D4E73B22CF1")
        self.assertTrue(res_upper["valid"])
        self.assertEqual(res_upper["tunnel_id"], uuid_std)
        self.assertEqual(res_upper["cname_target"], f"{uuid_std}.cfargotunnel.com")

        # 32-char hex UUID
        hex32 = "c7b7444749514d37882f2d4e73b22cf1"
        res_hex = parse_tunnel_token(hex32)
        self.assertTrue(res_hex["valid"])
        self.assertEqual(res_hex["tunnel_id"], hex32)
        self.assertEqual(res_hex["cname_target"], f"{hex32}.cfargotunnel.com")

    def test_parse_tunnel_token_cname_target(self):
        uuid_std = "c7b74447-4951-4d37-882f-2d4e73b22cf1"
        cname = f"{uuid_std}.cfargotunnel.com"
        res = parse_tunnel_token(cname)
        self.assertTrue(res["valid"])
        self.assertEqual(res["tunnel_id"], uuid_std)
        self.assertEqual(res["cname_target"], f"{uuid_std}.cfargotunnel.com")

        # With URL scheme
        res_url = parse_tunnel_token(f"https://{cname}/")
        self.assertTrue(res_url["valid"])
        self.assertEqual(res_url["tunnel_id"], uuid_std)
        self.assertEqual(res_url["cname_target"], f"{uuid_std}.cfargotunnel.com")

        # Wildcard / prefix target
        res_wildcard = parse_tunnel_token("*.cfargotunnel.com")
        self.assertTrue(res_wildcard["valid"])
        self.assertEqual(res_wildcard["cname_target"], "*.cfargotunnel.com")

    def test_parse_tunnel_token_invalid(self):
        self.assertFalse(parse_tunnel_token("not-a-token")["valid"])
        self.assertFalse(parse_tunnel_token("")["valid"])
        self.assertFalse(parse_tunnel_token(None)["valid"])
        # Base64 string that isn't JSON
        self.assertFalse(parse_tunnel_token(base64.b64encode(b"random-bytes").decode())["valid"])

    @patch("subprocess.run")
    def test_check_cloudflare_containers(self, mock_run):
        mock_output = (
            "cid1\taio-tunnel\tcloudflare/cloudflared:latest\tUp 3 hours\trunning\ttunnel run\tcom.docker.compose.service=cloudflared\n"
            "cid2\tdocktun-cloudflared\tcloudflare/cloudflared:latest\tUp 5 days\trunning\ttunnel run\tdocktun.provider=cloudflare\n"
            "cid3\tflaresolverr\tghcr.io/flaresolverr:latest\tUp 3 hours\trunning\t\t\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

        res = check_cloudflare_containers()
        self.assertTrue(res["available"])
        self.assertTrue(res["has_external"])
        self.assertEqual(len(res["external_connectors"]), 1)
        self.assertEqual(res["external_connectors"][0]["name"], "docktun-cloudflared")
        self.assertIsNotNone(res["local_tunnel"])
        self.assertEqual(res["local_tunnel"]["name"], "aio-tunnel")
        self.assertTrue(res["local_tunnel"]["is_local"])

    @patch("subprocess.run")
    def test_check_cloudflare_containers_derives_project_passively_from_hostname(self, mock_run):
        mock_output = (
            "cfother999999\taio-tunnel\tcloudflare/cloudflared:latest\tUp 2 hours\trunning\ttunnel run\t"
            "com.docker.compose.project=other-stack,com.docker.compose.service=cloudflared\n"
            "cflocal123456\taio-tunnel\tcloudflare/cloudflared:latest\tUp 1 hour\trunning\ttunnel run\t"
            "com.docker.compose.project=my-stack,com.docker.compose.service=cloudflared\n"
            "portalabcdef1\taio-portal\tghcr.io/example/portal:latest\tUp 1 hour\trunning\tpython portal.py\t"
            "com.docker.compose.project=my-stack,com.docker.compose.service=portal\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

        with patch.dict(
            os.environ,
            {
                "AIO_PROJECT_NAME": "",
                "COMPOSE_PROJECT_NAME": "",
                "HOSTNAME": "portalabcdef1234567890",
            },
        ):
            res = check_cloudflare_containers()

        mock_run.assert_called_once()
        self.assertTrue(res["available"])
        self.assertEqual(res["local_tunnel"]["id"], "cflocal123456")
        self.assertTrue(res["local_tunnel"]["is_local"])
        self.assertTrue(res["has_external"])
        self.assertEqual(len(res["external_connectors"]), 1)
        self.assertEqual(res["external_connectors"][0]["id"], "cfother999999")
        self.assertFalse(res["external_connectors"][0]["is_local"])

    def test_push_cloudflare_dns_missing_args(self):
        res1 = push_cloudflare_dns("", "watch.example.com", "target.cfargotunnel.com")
        self.assertFalse(res1["success"])
        self.assertIn("API Token is required", res1["error"])

        # Localhost and local IPs must return public domain error
        for bad_host in ("localhost", "127.0.0.1", "192.168.1.1", "10.0.0.1", "192.168.x.x"):
            res = push_cloudflare_dns("api_token_123", bad_host, "target.cfargotunnel.com")
            self.assertFalse(res["success"])
            self.assertEqual(res["error"], "Cloudflare DNS requires a public domain name (e.g. watch.yourdomain.com), not a local IP address.")

        # Non-IP without dots
        res_nodot = push_cloudflare_dns("api_token_123", "myinternalhost", "target.cfargotunnel.com")
        self.assertFalse(res_nodot["success"])
        self.assertIn("Enter a valid domain or subdomain", res_nodot["error"])

        res3 = push_cloudflare_dns("api_token_123", "watch.example.com", "")
        self.assertFalse(res3["success"])
        self.assertIn("target is required", res3["error"])

    @patch("urllib.request.urlopen")
    def test_push_cloudflare_dns_success_new_record(self, mock_urlopen):
        # 1. zones response
        zones_resp = json.dumps({
            "success": True,
            "result": [{"id": "zone-123", "name": "example.com"}]
        }).encode("utf-8")

        # 2. dns search (empty)
        dns_empty = json.dumps({"success": True, "result": []}).encode("utf-8")

        # 3. dns create response
        dns_created = json.dumps({
            "success": True,
            "result": {"id": "rec-999", "name": "watch.example.com", "type": "CNAME", "content": "tun123.cfargotunnel.com"}
        }).encode("utf-8")

        responses = [zones_resp, dns_empty, dns_created]

        mock_context = MagicMock()
        mock_context.__enter__.side_effect = lambda: MagicMock(
            read=lambda: responses.pop(0)
        )
        mock_urlopen.return_value = mock_context

        res = push_cloudflare_dns("valid_token", "watch.example.com", "tun123.cfargotunnel.com")
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "created")
        self.assertEqual(res["zone_name"], "example.com")
        self.assertEqual(res["record_id"], "rec-999")

    @patch("urllib.request.urlopen")
    def test_push_cloudflare_dns_success_update_existing(self, mock_urlopen):
        # 1. zones response
        zones_resp = json.dumps({
            "success": True,
            "result": [{"id": "zone-123", "name": "example.com"}]
        }).encode("utf-8")

        # 2. dns search (found existing)
        dns_existing = json.dumps({
            "success": True,
            "result": [{"id": "rec-existing", "name": "watch.example.com", "type": "CNAME"}]
        }).encode("utf-8")

        # 3. dns update response
        dns_updated = json.dumps({
            "success": True,
            "result": {"id": "rec-existing", "name": "watch.example.com", "type": "CNAME"}
        }).encode("utf-8")

        responses = [zones_resp, dns_existing, dns_updated]

        mock_context = MagicMock()
        mock_context.__enter__.side_effect = lambda: MagicMock(
            read=lambda: responses.pop(0)
        )
        mock_urlopen.return_value = mock_context

        res = push_cloudflare_dns("valid_token", "https://watch.example.com:3001/jellyfin", "tun123.cfargotunnel.com")
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "updated")
        self.assertEqual(res["hostname"], "watch.example.com")

    @patch("urllib.request.urlopen")
    def test_push_cloudflare_dns_with_explicit_zone_id(self, mock_urlopen):
        # When zone_id is explicitly provided, it skips querying /zones!
        # 1. dns search (empty)
        dns_empty = json.dumps({"success": True, "result": []}).encode("utf-8")
        # 2. dns create response
        dns_created = json.dumps({
            "success": True,
            "result": {"id": "rec-zone-direct", "name": "watch.mycustomzone.org", "type": "CNAME", "content": "tun123.cfargotunnel.com"}
        }).encode("utf-8")

        responses = [dns_empty, dns_created]

        mock_context = MagicMock()
        mock_context.__enter__.side_effect = lambda: MagicMock(
            read=lambda: responses.pop(0)
        )
        mock_urlopen.return_value = mock_context

        res = push_cloudflare_dns(
            "valid_token",
            "watch.mycustomzone.org",
            "tun123.cfargotunnel.com",
            zone_id="my-zone-id-abc"
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "created")
        self.assertEqual(res["record_id"], "rec-zone-direct")

    @patch("subprocess.run")
    def test_manage_local_tunnel(self, mock_run):
        # 1. Missing token returns error
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_TOKEN": ""}):
            res_no_tok = manage_local_tunnel("start", cwd=None)
            self.assertFalse(res_no_tok["success"])
            self.assertIn("not configured", res_no_tok["error"])

        # 2. Configured token succeeds
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_TOKEN": "eyJhIjoidGVzdCJ9"}):
            mock_run.return_value = MagicMock(returncode=0, stdout="running true", stderr="")
            res = manage_local_tunnel("start")
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "start")

        res_invalid = manage_local_tunnel("bad_action")
        self.assertFalse(res_invalid["success"])

    @patch("tools.cloudflare_helper.time.sleep")
    @patch("subprocess.run")
    def test_manager_tunnel_uses_existing_project_and_definition(self, mock_run, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            definition = Path(directory) / "compose.manager.yml"
            definition.write_text("services: {}")
            mock_run.side_effect = [MagicMock(returncode=0, stdout=""),
                                    MagicMock(returncode=0, stdout="generated-container-id"),
                                    MagicMock(returncode=0, stdout="running true")]
            with patch.dict(os.environ, {"AIO_PROJECT_NAME": "existing-stack"}):
                result = manage_local_tunnel("start", cwd=directory, token="fixture-token")
            self.assertTrue(result["success"])
            prefix = ["docker", "compose", "-p", "existing-stack", "-f", str(definition.resolve()), "--profile", "tunnel"]
            self.assertEqual(mock_run.call_args_list[0].args[0][:len(prefix)], prefix)
            self.assertEqual(mock_run.call_args_list[1].args[0][:len(prefix)], prefix)
            self.assertEqual(mock_run.call_args_list[2].args[0][-1], "generated-container-id")
            mock_run.reset_mock()
            with patch.dict(os.environ, {"AIO_PROJECT_NAME": "", "COMPOSE_PROJECT_NAME": ""}):
                result = manage_local_tunnel("start", cwd=directory, token="fixture-token")
            self.assertFalse(result["success"])
            mock_run.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_fetch_cloudflare_tunnel_token(self, mock_urlopen):
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.read.return_value = json.dumps({
            "success": True,
            "result": "eyJhIjoiYWNjb3VudCIsInQiOiJ0dW5uZWwtMTIzIiwicyI6InNlY3JldCJ9"
        }).encode("utf-8")
        mock_urlopen.return_value = mock_ctx

        res = fetch_cloudflare_tunnel_token("api_token_xyz", "acc_123", "tun_456")
        self.assertTrue(res["success"])
        self.assertEqual(res["token"], "eyJhIjoiYWNjb3VudCIsInQiOiJ0dW5uZWwtMTIzIiwicyI6InNlY3JldCJ9")

    @patch("tools.cloudflare_helper.time.sleep")
    @patch("subprocess.run")
    def test_tunnel_restart_applies_explicit_token(self, mock_run, _sleep):
        token = base64.b64encode(json.dumps({"a": "account", "t": "tunnel", "s": "secret"}).encode()).decode()
        mock_run.side_effect = [MagicMock(returncode=0, stdout="", stderr=""),
                                MagicMock(returncode=0, stdout="manager-tunnel-id", stderr=""),
                                MagicMock(returncode=0, stdout="running true", stderr="")]
        with patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_TOKEN": "old-token"}):
            result = manage_local_tunnel("restart", token=f"cloudflared tunnel run --token {token}")
        self.assertTrue(result["success"])
        call = mock_run.call_args_list[0]
        self.assertIn("--force-recreate", call.args[0])
        self.assertEqual(call.kwargs["env"]["CLOUDFLARE_TUNNEL_TOKEN"], token)
        self.assertNotIn(token, str(call.args[0]))
        self.assertNotIn("and connected", result["output"])
        self.assertEqual(mock_run.call_args_list[2].args[0][-1], "manager-tunnel-id")

    @patch("tools.cloudflare_helper.time.sleep")
    @patch("subprocess.run")
    def test_tunnel_inspect_failure_does_not_report_success(self, mock_run, _sleep):
        mock_run.side_effect = [MagicMock(returncode=0, stdout="", stderr=""),
                                MagicMock(returncode=0, stdout="manager-tunnel-id", stderr=""),
                                MagicMock(returncode=1, stdout="", stderr="not found")]
        result = manage_local_tunnel("start", token="fixture-token")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "unknown")

    @patch("tools.cloudflare_helper.time.sleep")
    @patch("subprocess.run")
    def test_tunnel_exited_container_is_failure(self, mock_run, _sleep):
        mock_run.side_effect = [MagicMock(returncode=0, stdout="", stderr=""),
                                MagicMock(returncode=0, stdout="manager-tunnel-id", stderr=""),
                                MagicMock(returncode=0, stdout="exited false", stderr=""),
                                MagicMock(returncode=0, stdout="invalid credentials", stderr=""),
                                MagicMock(returncode=0)]
        result = manage_local_tunnel("start", token="fixture-token")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "failed")

    @patch("tools.cloudflare_helper.time.sleep")
    @patch("subprocess.run")
    def test_manage_local_tunnel_ignores_hostname_without_project_env(self, mock_run, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "compose.manager.yml").write_text("services: {}")
            with patch.dict(
                os.environ,
                {
                    "AIO_PROJECT_NAME": "",
                    "COMPOSE_PROJECT_NAME": "",
                    "HOSTNAME": "cddbf58da603",
                },
            ):
                result = manage_local_tunnel("start", cwd=directory, token="fixture-token")
            self.assertFalse(result["success"])
            mock_run.assert_not_called()

    def test_validate_service_url(self):
        self.assertEqual(validate_service_url("http://host.docker.internal:3001/"), "http://host.docker.internal:3001")
        self.assertEqual(validate_service_url("127.0.0.1:3001"), "http://127.0.0.1:3001")
        self.assertEqual(validate_service_url("https://[::1]:3001"), "https://[::1]:3001")
        for bad in (
            "",
            "   ",
            "ftp://aiostreams:3000",
            "http://user:pass@127.0.0.1:3001",
            "http://127.0.0.1:3001/configure",
            "http://127.0.0.1:99999",
            "http://127.0.0.1:3001?a=1",
            "http://bad$var:3001",
            "http://bad'host:3001",
            'http://bad"host:3001',
            "http://bad`cmd`:3001",
            "http://bad\\host:3001",
            "http://bad\x07host:3001",
            "http://bad\x7fhost:3001",
            "http://bad\nhost:3001",
        ):
            with self.assertRaises(ValueError, msg=f"Expected ValueError for {bad!r}"):
                validate_service_url(bad)

    @patch("subprocess.run")
    def test_check_cloudflare_containers_topology_and_origin_recommendation(self, mock_run):
        # 1. External bridge connector -> host.docker.internal:3001
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="cid2\tdocktun-cf\tcloudflare/cloudflared:latest\tUp 2 hours\trunning\ttunnel run\tdocktun.provider=cloudflare\tdocktun_net\n",
            stderr="",
        )
        containers = check_cloudflare_containers()
        self.assertEqual(containers["external_connectors"][0]["network_mode"], "bridge")
        topo = recommend_cloudflare_origin(containers, env_vars={"PORT_AIOSTREAMS": "3001"})
        self.assertEqual(topo["connector_mode"], "external_bridge")
        self.assertEqual(topo["recommended_origin"], "http://host.docker.internal:3001")
        self.assertEqual(topo["aiometadata_origin"], "http://host.docker.internal:4005")
        self.assertIn("aiostreams:3000", topo["origin_warning"])

        # 2. External host-network connector -> 127.0.0.1:{PORT_AIOSTREAMS}
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="cid3\thost-cf\tcloudflare/cloudflared:latest\tUp 1 day\trunning\ttunnel run\t\thost\n",
            stderr="",
        )
        containers = check_cloudflare_containers()
        self.assertEqual(containers["external_connectors"][0]["network_mode"], "host")
        topo = recommend_cloudflare_origin(containers, env_vars={"PORT_AIOSTREAMS": "13001"})
        self.assertEqual(topo["connector_mode"], "external_host")
        self.assertEqual(topo["recommended_origin"], "http://127.0.0.1:13001")
        self.assertEqual(topo["aiometadata_origin"], "http://127.0.0.1:4005")

        # 3. Local aio-tunnel running on stremio-net -> aiostreams:3000
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="cid1\taio-tunnel\tcloudflare/cloudflared:latest\tUp 10 mins\trunning\ttunnel run\tcom.docker.compose.service=cloudflared\taio_stremio-net\n",
            stderr="",
        )
        containers = check_cloudflare_containers()
        self.assertEqual(containers["local_tunnel"]["network_mode"], "stremio-net")
        topo = recommend_cloudflare_origin(containers)
        self.assertEqual(topo["connector_mode"], "local_tunnel")
        self.assertEqual(topo["recommended_origin"], "http://aiostreams:3000")
        self.assertIsNone(topo["origin_warning"])

        # 4. No running connector / AIO DinD default -> host.docker.internal:3001
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        containers = check_cloudflare_containers()
        topo = recommend_cloudflare_origin(containers, env_vars={"CLOUDFLARE_ORIGIN_URL": "http://aiostreams:3000"})
        self.assertEqual(topo["connector_mode"], "none")
        self.assertEqual(topo["recommended_origin"], "http://host.docker.internal:3001")
        self.assertIn("aiostreams:3000", topo["origin_warning"])

    @patch("urllib.request.urlopen")
    def test_push_cloudflare_dns_repairs_stale_3000_rule_and_honors_service_url(self, mock_urlopen):
        zones_resp = json.dumps({"success": True, "result": [{"id": "zone-1", "name": "example.com"}]}).encode()
        dns_existing = json.dumps({"success": True, "result": [{"id": "rec-1", "name": "watch.example.com", "type": "CNAME"}]}).encode()
        dns_updated = json.dumps({"success": True, "result": {"id": "rec-1", "name": "watch.example.com"}}).encode()
        tunnel_cfg_get = json.dumps({
            "success": True,
            "result": {
                "config": {
                    "ingress": [
                        {"hostname": "watch.example.com", "service": "http://aiostreams:3000"},
                        {"service": "http_status:404"},
                    ]
                }
            }
        }).encode()
        tunnel_cfg_put = json.dumps({"success": True, "result": {}}).encode()

        captured_requests = []

        def fake_urlopen(req, timeout=10):
            captured_requests.append((req.get_method(), req.full_url, req.data))
            payload = [zones_resp, dns_existing, dns_updated, tunnel_cfg_get, tunnel_cfg_put][len(captured_requests) - 1]
            ctx = MagicMock()
            ctx.__enter__.return_value.read.return_value = payload
            return ctx

        mock_urlopen.side_effect = fake_urlopen

        res = push_cloudflare_dns(
            "valid_token",
            "watch.example.com",
            "tun123.cfargotunnel.com",
            account_id="acc-1",
            tunnel_id="tun-1",
            service_url="http://host.docker.internal:3001",
            aiometadata_hostname="aiometa.example.com",
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["ingress_configured"])
        self.assertTrue(res["repaired"])
        self.assertEqual(res["ingress_action"], "repaired")
        self.assertEqual(res["previous_service_url"], "http://aiostreams:3000")
        self.assertEqual(res["service_url"], "http://host.docker.internal:3001")
        self.assertIn("http://host.docker.internal:3001", res["message"])

        put_method, put_url, put_body = captured_requests[-1]
        self.assertEqual(put_method, "PUT")
        self.assertIn("/cfd_tunnel/tun-1/configurations", put_url)
        ingress = json.loads(put_body.decode())["config"]["ingress"]
        self.assertEqual(ingress[0], {"hostname": "watch.example.com", "service": "http://host.docker.internal:3001"})
        self.assertEqual(ingress[1], {"hostname": "aiometa.example.com", "service": "http://host.docker.internal:4005"})
        self.assertEqual(ingress[2], {"service": "http_status:404"})

    @patch("urllib.request.urlopen")
    def test_push_cloudflare_dns_skips_put_when_ingress_already_matches(self, mock_urlopen):
        dns_existing = json.dumps({"success": True, "result": [{"id": "rec-1", "name": "watch.example.com", "type": "CNAME"}]}).encode()
        dns_updated = json.dumps({"success": True, "result": {"id": "rec-1", "name": "watch.example.com"}}).encode()
        tunnel_cfg_get = json.dumps({
            "success": True,
            "result": {
                "config": {
                    "ingress": [
                        {"hostname": "watch.example.com", "service": "http://127.0.0.1:3001"},
                        {"service": "http_status:404"},
                    ]
                }
            }
        }).encode()
        responses = [dns_existing, dns_updated, tunnel_cfg_get]
        ctx = MagicMock()
        ctx.__enter__.side_effect = lambda: MagicMock(read=lambda: responses.pop(0))
        mock_urlopen.return_value = ctx

        res = push_cloudflare_dns(
            "valid_token",
            "watch.example.com",
            "tun123.cfargotunnel.com",
            account_id="acc-1",
            tunnel_id="tun-1",
            zone_id="zone-1",
            service_url="http://127.0.0.1:3001",
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["ingress_configured"])
        self.assertFalse(res["repaired"])
        self.assertEqual(res["ingress_action"], "unchanged")
        self.assertEqual(mock_urlopen.call_count, 3)

    def test_push_cloudflare_dns_rejects_invalid_service_url(self):
        res = push_cloudflare_dns(
            "valid_token",
            "watch.example.com",
            "tun123.cfargotunnel.com",
            service_url="http://host.docker.internal:3001/bad-path",
        )
        self.assertFalse(res["success"])
        self.assertIn("without a path", res["error"])

    def test_build_tunnel_origin_request_defaults_and_clamps_unsafe_keepalive(self):
        defaults = build_tunnel_origin_request()
        self.assertEqual(defaults["keepAliveTimeout"], 60)
        self.assertEqual(defaults["connectTimeout"], 30)
        self.assertEqual(defaults["keepAliveConnections"], 100)
        self.assertTrue(defaults["noHappyEyeballs"])

        preserved = build_tunnel_origin_request({"keepAliveTimeout": 45, "httpHostHeader": "media.example.dev"})
        self.assertEqual(preserved["keepAliveTimeout"], 45)
        self.assertEqual(preserved["httpHostHeader"], "media.example.dev")

        for unsafe in (0, -5, 120, 300, True):
            clamped = build_tunnel_origin_request({"keepAliveTimeout": unsafe})
            self.assertEqual(clamped["keepAliveTimeout"], 60)

    @patch("urllib.request.urlopen")
    def test_push_cloudflare_dns_sets_origin_request_and_repairs_unsafe_keepalive(self, mock_urlopen):
        dns_existing = json.dumps({"success": True, "result": [{"id": "rec-1", "name": "media.example.dev", "type": "CNAME"}]}).encode()
        dns_updated = json.dumps({"success": True, "result": {"id": "rec-1", "name": "media.example.dev"}}).encode()
        tunnel_cfg_get = json.dumps({
            "success": True,
            "result": {
                "config": {
                    "originRequest": {"keepAliveTimeout": 180},
                    "ingress": [
                        {"hostname": "media.example.dev", "service": "http://host.docker.internal:3001"},
                        {"service": "http_status:404"},
                    ],
                }
            }
        }).encode()
        tunnel_cfg_put = json.dumps({"success": True, "result": {}}).encode()

        captured = []

        def fake_urlopen(req, timeout=10):
            captured.append((req.get_method(), req.full_url, req.data))
            payload = [dns_existing, dns_updated, tunnel_cfg_get, tunnel_cfg_put][len(captured) - 1]
            ctx = MagicMock()
            ctx.__enter__.return_value.read.return_value = payload
            return ctx

        mock_urlopen.side_effect = fake_urlopen
        res = push_cloudflare_dns(
            "valid_token",
            "media.example.dev",
            "tun123.cfargotunnel.com",
            account_id="acc-1",
            tunnel_id="tun-1",
            zone_id="zone-1",
            service_url="http://host.docker.internal:3001",
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["repaired"])
        put_method, _, put_body = captured[-1]
        self.assertEqual(put_method, "PUT")
        cfg = json.loads(put_body.decode())["config"]
        self.assertEqual(cfg["originRequest"]["keepAliveTimeout"], 60)
        self.assertEqual(cfg["originRequest"]["connectTimeout"], 30)
        self.assertTrue(cfg["originRequest"]["noHappyEyeballs"])


if __name__ == "__main__":
    unittest.main()
