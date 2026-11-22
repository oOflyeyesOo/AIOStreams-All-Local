"""
Unit tests for Cloudflare Tunnel & DNS Automation Helper.
"""

import base64
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from tools.cloudflare_helper import (
    parse_tunnel_token,
    check_cloudflare_containers,
    push_cloudflare_dns,
    manage_local_tunnel
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
        mock_run.return_value = MagicMock(returncode=0, stdout="Started cloudflared", stderr="")
        res = manage_local_tunnel("start")
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "start")

        res_invalid = manage_local_tunnel("bad_action")
        self.assertFalse(res_invalid["success"])


if __name__ == "__main__":
    unittest.main()
