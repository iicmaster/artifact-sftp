#!/usr/bin/env python3
"""A real child-process stdio smoke test for the packaged MCP entrypoint."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]


class ArtifactSftpMcpStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_child_discovers_tools_and_reads_a_local_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            archive = project / "docs/artifacts/codex/private/stdio-smoke"
            archive.mkdir(parents=True)
            archive_file = archive / "index.html"
            archive_file.write_text("<html><body>stdio smoke</body></html>", encoding="utf-8")
            source = project / "dry-run.html"
            source.write_text("<html><body>dry run smoke</body></html>", encoding="utf-8")
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
            environment = {
                "HOME": str(home),
                "PATH": os.environ["PATH"],
                "ARTIFACT_SFTP_PLUGIN_ROOT": str(ROOT),
            }
            entrypoint = Path(sys.executable).with_name("artifact-sftp-mcp")
            self.assertTrue(entrypoint.is_file(), "the installed MCP entrypoint must exist")
            parameters = StdioServerParameters(
                command=str(entrypoint),
                cwd=temp,
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
                    dry_run_archive_exists = (project / "docs/artifacts/codex/private/dry-run-smoke").exists()

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


if __name__ == "__main__":
    unittest.main()
