#!/usr/bin/env python3
"""S3-compatible object storage transport for artifact-sftp (Cloudflare R2, AWS S3, MinIO).

Implements AWS Signature Version 4 (SigV4) using Python standard library with zero external dependencies.
Reads configuration strictly from ~/.config/artifact-sftp/config (0600) so secrets never land in argv.

Operations:
  exists RKEY
  upload LOCAL RPATH [VERSIONED_NAME] [VISIBILITY]
  get RKEY LOCAL
  delete RPATH
  list RBASE
  versions RPATH
  test_connection

Exit codes:
  0 ok | 1 not-found/failed | 4 storage refused or errored (distinct from not-found) | 10 internal bypass attempt
"""
import datetime
import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CONFIG = os.path.expanduser("~/.config/artifact-sftp/config")
MAX_BYTES = 5 * 1024 * 1024  # 5 MiB safety limit


def require_mcp_call():
    """Keep this transport internal to the Artifact SFTP MCP adapter."""
    if os.environ.get("ARTIFACT_SFTP_MCP_CALL") != "1":
        print(
            "s3_helper.py is internal to Artifact SFTP MCP; AI agents must use artifact_sftp.* tools.",
            file=sys.stderr,
        )
        raise SystemExit(10)


def read_cfg():
    cfg = {}
    if not os.path.isfile(CONFIG):
        sys.exit(f"config not found: {CONFIG}")
    with open(CONFIG, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(key, date_stamp, region_name, service_name):
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region_name.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service_name.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def _bounded_read(resp):
    """Read a response body without ever buffering more than MAX_BYTES."""
    length = resp.headers.get("Content-Length") if resp.headers is not None else None
    if length is not None and length.strip().isdigit() and int(length) > MAX_BYTES:
        sys.exit(f"response exceeds {MAX_BYTES} byte safety ceiling (Content-Length: {length})")
    data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        sys.exit(f"response exceeds {MAX_BYTES} byte safety ceiling (streamed past the limit)")
    return data


class S3Client:
    def __init__(self, cfg):
        self.endpoint = cfg.get("S3_ENDPOINT", "").rstrip("/")
        self.bucket = cfg.get("S3_BUCKET", "")
        self.access_key = cfg.get("S3_ACCESS_KEY_ID", "")
        self.secret_key = cfg.get("S3_SECRET_ACCESS_KEY", "")
        self.region = cfg.get("S3_REGION", "auto")
        if not self.endpoint or not self.bucket or not self.access_key or not self.secret_key:
            sys.exit("missing required S3 config: S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY")

    def _request(self, method, path, query_params=None, headers=None, body=b"", timeout=30):
        if headers is None:
            headers = {}
        if query_params is None:
            query_params = {}

        # Normalize URL path
        norm_path = "/" + self.bucket + ("/" + path.lstrip("/") if path.lstrip("/") else "")
        parsed_endpoint = urllib.parse.urlparse(self.endpoint)
        host = parsed_endpoint.netloc
        scheme = parsed_endpoint.scheme or "https"

        # Canonical URI encoding (RFC 3986)
        canonical_uri = urllib.parse.quote(norm_path, safe="/~")

        # Query string with RFC 3986 encoding (%20 instead of +)
        sorted_params = sorted(query_params.items())
        query_parts = []
        for k, v in sorted_params:
            k_enc = urllib.parse.quote(str(k), safe="~")
            v_enc = urllib.parse.quote(str(v), safe="~")
            query_parts.append(f"{k_enc}={v_enc}")
        query_string = "&".join(query_parts)

        # Wire URL using exact canonical URI path
        url = f"{scheme}://{host}{canonical_uri}" + (f"?{query_string}" if query_string else "")

        now = datetime.datetime.now(datetime.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        payload_hash = hashlib.sha256(body).hexdigest()

        # Prepare headers for SigV4
        canonical_headers_dict = {
            "host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
        }
        for k, v in headers.items():
            canonical_headers_dict[k.lower().strip()] = str(v).strip()

        sorted_header_keys = sorted(canonical_headers_dict.keys())
        canonical_headers = "".join(f"{k}:{canonical_headers_dict[k]}\n" for k in sorted_header_keys)
        signed_headers = ";".join(sorted_header_keys)

        canonical_request = (
            f"{method}\n"
            f"{canonical_uri}\n"
            f"{query_string}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = (
            f"{algorithm}\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(self.secret_key, date_stamp, self.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = (
            f"{algorithm} "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        req_headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": auth_header,
        }
        for k, v in headers.items():
            req_headers[k] = v

        req = urllib.request.Request(
            url,
            data=body if method in ("PUT", "POST") else None,
            headers=req_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, _bounded_read(resp), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, _bounded_read(e), e.headers
        except Exception as e:
            sys.exit(f"S3 request failed ({method} {path}): {e}")

    def head_object(self, key):
        status, resp_body, _ = self._request("HEAD", key)
        if status == 200:
            return True
        if status == 404:
            return False
        # Storage refused or errored: exit 4 so callers never confuse "probe
        # failed" with "probe answered 404" — the overwrite guard depends on
        # that distinction before it may treat a slug as absent.
        print(f"S3 HEAD failed ({status}): {resp_body.decode('utf-8', errors='replace')}", file=sys.stderr)
        sys.exit(4)

    def put_object(self, key, data, content_type="text/html; charset=utf-8", cache_control="private, no-cache"):
        headers = {
            "Content-Type": content_type,
            "Cache-Control": cache_control,
        }
        status, resp_body, _ = self._request("PUT", key, headers=headers, body=data)
        if status not in (200, 204):
            sys.exit(f"S3 PUT failed ({status}): {resp_body.decode('utf-8', errors='replace')}")

    def get_object(self, key):
        status, resp_body, _ = self._request("GET", key)
        if status == 404:
            return None
        if status != 200:
            sys.exit(f"S3 GET failed ({status}): {resp_body.decode('utf-8', errors='replace')}")
        return resp_body

    def delete_object(self, key):
        status, resp_body, _ = self._request("DELETE", key)
        if status not in (200, 204, 404):
            sys.exit(f"S3 DELETE failed ({status}): {resp_body.decode('utf-8', errors='replace')}")

    def list_objects_v2_paged(self, prefix="", delimiter=""):
        """Lists all objects handling pagination tokens (IsTruncated / NextContinuationToken)."""
        all_keys = []
        all_common_prefixes = []
        continuation_token = None

        while True:
            params = {"list-type": "2"}
            if prefix:
                params["prefix"] = prefix
            if delimiter:
                params["delimiter"] = delimiter
            if continuation_token:
                params["continuation-token"] = continuation_token

            status, resp_body, _ = self._request("GET", "", query_params=params)
            if status != 200:
                sys.exit(f"S3 list objects failed ({status}): {resp_body.decode('utf-8', errors='replace')}")

            root = ET.fromstring(resp_body)
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            for elem in root.findall(f"{ns}Contents"):
                key_elem = elem.find(f"{ns}Key")
                if key_elem is not None and key_elem.text:
                    all_keys.append(key_elem.text)

            for elem in root.findall(f"{ns}CommonPrefixes"):
                prefix_elem = elem.find(f"{ns}Prefix")
                if prefix_elem is not None and prefix_elem.text:
                    all_common_prefixes.append(prefix_elem.text)

            is_truncated_elem = root.find(f"{ns}IsTruncated")
            is_truncated = is_truncated_elem is not None and is_truncated_elem.text == "true"

            if not is_truncated:
                break

            next_token_elem = root.find(f"{ns}NextContinuationToken")
            if next_token_elem is not None and next_token_elem.text:
                continuation_token = next_token_elem.text
            else:
                break

        return all_keys, all_common_prefixes

    def test_connection(self):
        status, _, _ = self._request("GET", "", query_params={"list-type": "2", "max-keys": "1"})
        return status == 200


def main():
    require_mcp_call()
    if len(sys.argv) < 2:
        sys.exit("usage: s3_helper.py exists|upload|get|delete|list|versions|test_connection [ARGS...]")

    op = sys.argv[1]
    cfg = read_cfg()
    client = S3Client(cfg)

    if op == "test_connection":
        if client.test_connection():
            print("OK")
            sys.exit(0)
        else:
            sys.exit(1)

    elif op == "exists":
        if len(sys.argv) < 3:
            sys.exit("usage: s3_helper.py exists <key>")
        key = sys.argv[2].lstrip("/")
        if not key.endswith("index.html"):
            key = key.rstrip("/") + "/index.html"
        if client.head_object(key):
            sys.exit(0)
        else:
            sys.exit(1)

    elif op == "upload":
        if len(sys.argv) < 4:
            sys.exit("usage: s3_helper.py upload <local_file> <prefix> [versioned_name] [visibility]")
        local_file = sys.argv[2]
        prefix = sys.argv[3].strip("/")
        vname = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != "-" else None
        visibility = sys.argv[5] if len(sys.argv) > 5 else "private"

        with open(local_file, "rb") as f:
            data = f.read()

        if len(data) > MAX_BYTES:
            sys.exit(f"artifact size exceeds 5 MiB limit ({len(data)} bytes)")

        # Determine cache control based on visibility
        if visibility == "public":
            index_cache = "public, max-age=300"
            vname_cache = "public, max-age=31536000, immutable"
        else:
            index_cache = "private, no-cache"
            vname_cache = "private, no-cache"

        # Upload the immutable snapshot FIRST: if it fails, the live index is
        # left untouched, so the served artifact never loses its promised
        # snapshot while the manifest still points at the previous version.
        if vname:
            client.put_object(
                f"{prefix}/{vname}",
                data,
                content_type="text/html; charset=utf-8",
                cache_control=vname_cache,
            )

        client.put_object(
            f"{prefix}/index.html",
            data,
            content_type="text/html; charset=utf-8",
            cache_control=index_cache,
        )

    elif op == "get":
        if len(sys.argv) < 4:
            sys.exit("usage: s3_helper.py get <remote_key> <local_file>")
        rkey = sys.argv[2].lstrip("/")
        lfile = sys.argv[3]
        data = client.get_object(rkey)
        if data is None:
            sys.exit(1)
        if len(data) > MAX_BYTES:
            sys.exit(f"downloaded object exceeds 5 MiB safety ceiling ({len(data)} bytes)")
        with open(lfile, "wb") as f:
            f.write(data)

    elif op == "delete":
        if len(sys.argv) < 3:
            sys.exit("usage: s3_helper.py delete <prefix>")
        prefix = sys.argv[2].strip("/") + "/"
        keys, _ = client.list_objects_v2_paged(prefix=prefix)
        for key in keys:
            client.delete_object(key)

    elif op == "versions":
        if len(sys.argv) < 3:
            sys.exit("usage: s3_helper.py versions <prefix>")
        prefix = sys.argv[2].strip("/") + "/"
        keys, _ = client.list_objects_v2_paged(prefix=prefix)
        for key in sorted(keys):
            filename = key[len(prefix):]
            if filename:
                print(filename)

    elif op == "list":
        if len(sys.argv) < 3:
            sys.exit("usage: s3_helper.py list <base_prefix>")
        base = sys.argv[2].strip("/")
        for vis in ("private", "public"):
            prefix = f"{base}/{vis}/"
            _, common_prefixes = client.list_objects_v2_paged(prefix=prefix, delimiter="/")
            for cp in sorted(common_prefixes):
                sub = cp[len(prefix):].rstrip("/")
                if sub:
                    print(f"{vis}/{sub}")

    else:
        sys.exit(f"unknown op: {op}")


if __name__ == "__main__":
    main()
