"""Offline SigV4 and S3 driver tests for the artifact-sftp publisher helper."""

import hashlib
import hmac
import importlib.util
import io
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
import urllib.parse
from pathlib import Path

# Load s3_helper module dynamically
HELPER_PATH = Path(__file__).resolve().parent.parent / "skills" / "artifact-sftp" / "scripts" / "s3_helper.py"
spec = importlib.util.spec_from_file_location("s3_helper", str(HELPER_PATH))
s3_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s3_helper)

CONFIG = {
    "S3_ENDPOINT": "https://account123.r2.cloudflarestorage.com",
    "S3_BUCKET": "my-artifacts",
    "S3_ACCESS_KEY_ID": "TEST-ACCESS-KEY-ID-EXAMPLE",
    "S3_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # pragma: allowlist secret
    "S3_REGION": "auto",
}


def fake_response(payload: bytes = b"") -> io.BytesIO:
    resp = io.BytesIO(payload)
    resp.status = 200
    resp.headers = {}
    return resp


class S3HelperTests(unittest.TestCase):
    def test_mcp_environment_gate(self) -> None:
        """s3_helper refuses direct CLI invocation without ARTIFACT_SFTP_MCP_CALL=1."""
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                s3_helper.require_mcp_call()
            self.assertEqual(ctx.exception.code, 10)
        with unittest.mock.patch.dict(os.environ, {"ARTIFACT_SFTP_MCP_CALL": "1"}):
            s3_helper.require_mcp_call()  # Should not raise

    def test_sigv4_aws_get_vanilla_official_vector(self) -> None:
        """s3_helper's key derivation and signature reproduce the official AWS get-vanilla test vector."""
        # Official AWS SigV4 get-vanilla test vector (published example values, not credentials):
        secret_key = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
        date_stamp = "20150830"
        region = "us-east-1"
        service = "service"

        signing_key = s3_helper._get_signature_key(secret_key, date_stamp, region, service)
        expected_k_signing_hex = "938127b5336810ddb6a5d6af445fcac9e371f9ed418ed386b022aed82901be75"  # pragma: allowlist secret
        self.assertEqual(signing_key.hex(), expected_k_signing_hex)

        # Official Canonical Request string to sign for get-vanilla
        string_to_sign = (
            "AWS4-HMAC-SHA256\n"
            "20150830T123600Z\n"
            "20150830/us-east-1/service/aws4_request\n"
            "bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63"  # pragma: allowlist secret
        )
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        expected_sig = "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"  # pragma: allowlist secret
        self.assertEqual(signature, expected_sig)

    def test_sigv4_aws_iam_documentation_vector(self) -> None:
        """s3_helper's key derivation matches the AWS documentation example (IAM)."""
        secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
        date_stamp = "20150830"
        region = "us-east-1"
        service = "iam"

        signing_key = s3_helper._get_signature_key(secret_key, date_stamp, region, service)
        expected_k_signing_hex = "2c94c0cf5378ada6887f09bb697df8fc0affdb34ba1cdd5bda32b664bd55b73c"  # pragma: allowlist secret
        self.assertEqual(signing_key.hex(), expected_k_signing_hex)

    def test_s3_client_put_and_cache_control(self) -> None:
        """S3 PUT request headers and cache-control semantics for public vs private artifacts."""
        client = s3_helper.S3Client(CONFIG)
        captured_requests = []

        def mock_urlopen(req, timeout=30):
            captured_requests.append(req)
            return fake_response()

        with unittest.mock.patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
            # 1. Test Put Private Object
            client.put_object("codex/private/test-slug/index.html", b"<h1>Private</h1>", cache_control="private, no-cache")
            # 2. Test Put Public Object
            client.put_object("codex/public/test-slug/index.html", b"<h1>Public</h1>", cache_control="public, max-age=300")

        self.assertEqual(len(captured_requests), 2)
        req1, req2 = captured_requests
        self.assertEqual(req1.get_method(), "PUT")
        self.assertEqual(req1.get_header("Cache-control"), "private, no-cache")
        self.assertEqual(req1.get_header("Content-type"), "text/html; charset=utf-8")
        self.assertIn("AWS4-HMAC-SHA256", req1.headers["Authorization"])
        self.assertEqual(req2.get_header("Cache-control"), "public, max-age=300")

    def test_s3_client_list_pagination(self) -> None:
        """list_objects_v2_paged correctly iterates over multiple continuation tokens."""
        client = s3_helper.S3Client(CONFIG)

        page1_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
            <IsTruncated>true</IsTruncated>
            <NextContinuationToken>token-page-2</NextContinuationToken>
            <Contents><Key>codex/public/doc1/index.html</Key></Contents>
            <Contents><Key>codex/public/doc2/index.html</Key></Contents>
        </ListBucketResult>"""

        page2_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
            <IsTruncated>false</IsTruncated>
            <Contents><Key>codex/public/doc3/index.html</Key></Contents>
        </ListBucketResult>"""

        calls = []

        def mock_urlopen(req, timeout=30):
            calls.append(req.full_url)
            return fake_response(page2_xml if "continuation-token=token-page-2" in req.full_url else page1_xml)

        with unittest.mock.patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
            keys, _ = client.list_objects_v2_paged(prefix="codex/public/")

        self.assertEqual(len(calls), 2)
        self.assertEqual(keys, [
            "codex/public/doc1/index.html",
            "codex/public/doc2/index.html",
            "codex/public/doc3/index.html",
        ])

    def test_s3_client_head_status(self) -> None:
        """HEAD distinguishes 200 (exists) from 404 (absent) and raises on 403."""
        client = s3_helper.S3Client(CONFIG)

        # 200 OK
        with unittest.mock.patch.object(urllib.request, "urlopen", return_value=fake_response()):
            self.assertIs(client.head_object("key.html"), True)

        # 404 Not Found
        def mock_404(req, timeout=30):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"Not Found"))

        with unittest.mock.patch.object(urllib.request, "urlopen", side_effect=mock_404):
            self.assertIs(client.head_object("key.html"), False)

        # 403 Forbidden -> SystemExit
        def mock_403(req, timeout=30):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"Access Denied"))

        with unittest.mock.patch.object(urllib.request, "urlopen", side_effect=mock_403):
            with self.assertRaises(SystemExit) as ctx:
                client.head_object("key.html")
            self.assertEqual(ctx.exception.code, 4)

    def test_upload_orders_snapshot_before_live_index(self) -> None:
        """The immutable snapshot uploads first: a failed snapshot PUT must
        never leave the live index serving content without its snapshot."""
        client = s3_helper.S3Client(CONFIG)
        uploaded_keys = []

        def mock_urlopen(req, timeout=30):
            uploaded_keys.append(urllib.parse.unquote(req.full_url))
            return fake_response()

        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "artifact.html"
            local.write_bytes(b"<html></html>")
            config_file = Path(temp) / "config"
            config_file.write_text(
                "\n".join(f"{key}={value}" for key, value in CONFIG.items()) + "\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.object(s3_helper, "CONFIG", str(config_file)), \
                 unittest.mock.patch.object(sys, "argv", [
                     "s3_helper.py", "upload", str(local), "codex/private/slug",
                     "slug--1--20260101T000000Z.html", "private",
                 ]), \
                 unittest.mock.patch.dict(os.environ, {"ARTIFACT_SFTP_MCP_CALL": "1"}), \
                 unittest.mock.patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
                s3_helper.main()

        self.assertEqual(len(uploaded_keys), 2)
        self.assertIn("slug--1--20260101T000000Z.html", uploaded_keys[0])
        self.assertIn("index.html", uploaded_keys[1])

    def test_get_rejects_oversized_content_length_before_reading(self) -> None:
        """A Content-Length above the 5 MiB ceiling is rejected before buffering the body."""
        client = s3_helper.S3Client(CONFIG)
        oversized = fake_response()
        oversized.headers = {"Content-Length": str(6 * 1024 * 1024)}
        with unittest.mock.patch.object(urllib.request, "urlopen", return_value=oversized):
            with self.assertRaises(SystemExit) as ctx:
                client.get_object("key.html")
        self.assertIn("safety ceiling", str(ctx.exception))

    def test_get_rejects_bodies_streaming_past_the_ceiling(self) -> None:
        """Without Content-Length, reading stops just past the ceiling instead of buffering the object."""
        client = s3_helper.S3Client(CONFIG)
        streaming = fake_response(b"A" * (5 * 1024 * 1024 + 1))
        streaming.headers = {}
        with unittest.mock.patch.object(urllib.request, "urlopen", return_value=streaming):
            with self.assertRaises(SystemExit) as ctx:
                client.get_object("key.html")
        self.assertIn("safety ceiling", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
