#!/usr/bin/env python3
"""A real child-process stdio smoke test for the packaged MCP launcher."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]


class ArtifactSftpMcpStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_packaged_mcp_launcher_discovers_tools_reads_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            archive = project / "docs/artifacts/codex/private/stdio-smoke"
            archive.mkdir(parents=True)
            archive_file = archive / "index.html"
            archive_file.write_text("<html><body>stdio smoke</body></html>", encoding="utf-8")
            source = project / "dry-run.html"
            source.write_text("<html><head><title>ไทย</title></head><body>สวัสดี MCP</body></html>", encoding="utf-8")
            home = Path(temp) / "home"
            config_dir = home / ".config/artifact-sftp"
            config_dir.mkdir(parents=True)
            config_dir.chmod(0o700)
            config = config_dir / "config"
            config.write_text(
                "\n".join(
                    (
                        "SFTP_HOST=sftp.example",
                        "SFTP_USER=artifact",
                        "SFTP_PORT=22",
                        "REMOTE_DIR=/files",
                        "PUBLIC_BASE_URL=https://artifacts.example",
                        "DEFAULT_TOOL=codex",
                        "SSH_KEY=/tmp/nonexistent-key-not-used-by-dry-run",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            config.chmod(0o600)
            known_hosts = config_dir / "known_hosts"
            known_hosts.write_text("placeholder\n", encoding="utf-8")
            known_hosts.chmod(0o600)
            mock_bin = Path(temp) / "mock-bin"
            mock_bin.mkdir()
            mock_sftp = mock_bin / "sftp"
            mock_sftp.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
batch='' prev=''
for argument in "$@"; do
  if [ "$prev" = '-b' ]; then batch=$argument; fi
  prev=$argument
done
if [ -n "$batch" ]; then
  source=$(sed -n 's/^put "\\([^"\\]*\\)".*/\\1/p' "$batch" | tail -1)
  if [ -n "$source" ]; then cp "$source" "$HOME/last-put.html"; fi
  if head -n1 "$batch" | grep -q '^ls '; then exit 1; fi
fi
exit 0
""",
                encoding="utf-8",
            )
            mock_curl = mock_bin / "curl"
            mock_curl.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
out='' hdr='' prev=''
for argument in "$@"; do
  case "$prev" in
    -o) out=$argument ;;
    -D) hdr=$argument ;;
  esac
  prev=$argument
done
[ -z "$out" ] || : > "$out"
[ -z "$hdr" ] || printf 'HTTP/2 403 \\n' > "$hdr"
printf '403'
""",
                encoding="utf-8",
            )
            mock_sftp.chmod(0o700)
            mock_curl.chmod(0o700)
            plugin_data = Path(temp) / "plugin-data"
            mcp_manifest = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
            declared_server = mcp_manifest["mcpServers"]["artifact-sftp"]
            command = declared_server["command"]
            self.assertTrue(command.startswith("./"))
            launcher = (ROOT / command.removeprefix("./")).resolve()
            self.assertTrue(launcher.is_file(), "mcp.json must point to a packaged launcher")
            host_cwd = declared_server["cwd"].replace("${PLUGIN_ROOT}", str(ROOT))
            environment = {
                "HOME": str(home),
                "PATH": f"{mock_bin}{os.pathsep}{os.environ['PATH']}",
                "PLUGIN_ROOT": str(ROOT),
                "PLUGIN_DATA": str(plugin_data),
            }
            for name, value in declared_server["env"].items():
                environment[name] = value.replace("${PLUGIN_ROOT}", str(ROOT))
            parameters = StdioServerParameters(
                command=str(launcher),
                cwd=host_cwd,
                env=environment,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    names = {tool.name for tool in listing.tools}
                    setup_status = await session.call_tool("artifact_sftp.setup_status", {})
                    response = await session.call_tool(
                        "artifact_sftp.read",
                        {
                            "project_path": str(project),
                            "reference": "https://artifacts.example/codex/private/stdio-smoke/",
                        },
                    )
                    dry_run = await session.call_tool(
                        "artifact_sftp.publish",
                        {
                            "project_path": str(project),
                            "source_path": str(source),
                            "slug": "dry-run-smoke",
                            "tool": "codex",
                            "dry_run": True,
                        },
                    )
                    published = await session.call_tool(
                        "artifact_sftp.publish",
                        {
                            "project_path": str(project),
                            "source_path": str(source),
                            "slug": "confirmed-smoke",
                            "tool": "codex",
                            "confirm": True,
                        },
                    )
                    dry_run_archive_exists = (project / "docs/artifacts/codex/private/dry-run-smoke").exists()
                    plugin_venv_exists = (plugin_data / "venv").is_dir()
                    published_archive = project / "docs/artifacts/codex/private/confirmed-smoke/index.html"
                    published_html = published_archive.read_text(encoding="utf-8")
                    uploaded_html = (home / "last-put.html").read_text(encoding="utf-8")

        self.assertIn("artifact_sftp.publish", names)
        self.assertIn("artifact_sftp.read", names)
        self.assertIn("artifact_sftp.setup_status", names)
        self.assertFalse(setup_status.is_error)
        self.assertFalse(setup_status.structured_content["result"]["ready"])
        self.assertFalse(response.is_error)
        self.assertEqual(response.structured_content["result"]["content"], "<html><body>stdio smoke</body></html>")
        self.assertFalse(dry_run.is_error)
        self.assertEqual(dry_run.structured_content["result"]["status"], "dry_run")
        self.assertEqual(dry_run.structured_content["result"]["url"], "https://artifacts.example/codex/private/dry-run-smoke/")
        self.assertFalse(dry_run_archive_exists)
        self.assertFalse(published.is_error)
        self.assertEqual(published.structured_content["result"]["status"], "published")
        self.assertIn('data-artifact-sftp-font="sarabun"', published_html)
        self.assertIn("fonts.googleapis.com/css2?family=Sarabun", published_html)
        self.assertEqual(uploaded_html, published_html)
        self.assertTrue(plugin_venv_exists)


if __name__ == "__main__":
    unittest.main()
