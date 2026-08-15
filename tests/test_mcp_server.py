#!/usr/bin/env python3
"""Offline MCP contract tests for Artifact SFTP's local stdio adapter."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from artifact_sftp_mcp.server import build_server  # noqa: E402
from artifact_sftp_mcp.service import (  # noqa: E402
    ArtifactSftpService,
    CommandResult,
)


class FakeRunner:
    def __init__(self, *results: CommandResult) -> None:
        self.results = list(results)
        self.calls: list[tuple[tuple[str, ...], Path, float]] = []

    def run(self, args: list[str] | tuple[str, ...], *, cwd: Path, timeout: float) -> CommandResult:
        self.calls.append((tuple(args), cwd, timeout))
        if not self.results:
            raise AssertionError(f"unexpected command: {args}")
        return self.results.pop(0)


def command_result(returncode: int, *, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


def make_project(base: Path) -> tuple[Path, Path, Path, Path]:
    project = base / "project"
    project.mkdir()
    source = project / "report.html"
    source.write_text("<!doctype html><html><body>source</body></html>", encoding="utf-8")
    archive = project / "docs/artifacts/codex/private/report"
    archive.mkdir(parents=True)
    current = archive / "index.html"
    current.write_text("<html><body>สวัสดี from local archive</body></html>", encoding="utf-8")
    snapshot = archive / "report--1--20260810T120000Z.html"
    snapshot.write_bytes(current.read_bytes())
    return project, source, current, snapshot


class ArtifactSftpMcpTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, server, name: str, arguments: dict):
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    async def test_tool_catalog_uses_only_safe_v1_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            server = build_server(
                ArtifactSftpService(plugin_root=ROOT, runner=FakeRunner(), start_cwd=project)
            )
            async with Client(server) as client:
                listing = await client.list_tools()

        tools = {tool.name: tool for tool in listing.tools}
        self.assertEqual(
            set(tools),
            {
                "artifact_sftp.setup_status",
                "artifact_sftp.setup",
                "artifact_sftp.publish",
                "artifact_sftp.unpublish",
                "artifact_sftp.read",
                "artifact_sftp.list",
            },
        )
        publish_properties = tools["artifact_sftp.publish"].input_schema["properties"]
        self.assertNotIn("allow_sensitive", publish_properties)
        self.assertNotIn("force", publish_properties)
        self.assertNotIn("password", publish_properties)
        self.assertNotIn("secret", publish_properties)
        unpublish_properties = tools["artifact_sftp.unpublish"].input_schema["properties"]
        self.assertNotIn("force", unpublish_properties)
        self.assertNotIn("password", unpublish_properties)
        self.assertTrue(tools["artifact_sftp.unpublish"].annotations.destructive_hint)
        self.assertNotIn("reconfigure", tools["artifact_sftp.setup"].input_schema["properties"])
        self.assertIn("verify_connection", tools["artifact_sftp.setup_status"].input_schema["properties"])
        self.assertIn("verify_connection", tools["artifact_sftp.setup"].input_schema["properties"])
        self.assertEqual(
            tools["artifact_sftp.setup_status"].input_schema["properties"]["verify_connection"]["type"],
            "boolean",
        )
        self.assertEqual(
            tools["artifact_sftp.setup"].input_schema["properties"]["verify_connection"]["type"],
            "boolean",
        )
        self.assertTrue(tools["artifact_sftp.read"].annotations.read_only_hint)
        self.assertTrue(tools["artifact_sftp.list"].annotations.read_only_hint)
        self.assertTrue(tools["artifact_sftp.publish"].annotations.open_world_hint)
        self.assertTrue(tools["artifact_sftp.unpublish"].annotations.open_world_hint)
        self.assertTrue(tools["artifact_sftp.setup_status"].annotations.open_world_hint)
        self.assertTrue(tools["artifact_sftp.setup"].annotations.open_world_hint)

    async def test_publish_requires_confirmation_without_starting_a_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, source, _, _ = make_project(Path(temp))
            fake = FakeRunner()
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.publish",
                {
                    "project_path": str(project),
                    "source_path": str(source),
                    "slug": "report",
                    "tool": "codex",
                },
            )

        self.assertTrue(response.is_error)
        self.assertEqual(response.structured_content["error"]["code"], "confirmation_required")
        self.assertEqual(fake.calls, [])

    async def test_public_publish_requires_its_own_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, source, _, _ = make_project(Path(temp))
            fake = FakeRunner()
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.publish",
                {
                    "project_path": str(project),
                    "source_path": str(source),
                    "slug": "report",
                    "tool": "codex",
                    "visibility": "public",
                    "confirm": True,
                },
            )

        self.assertTrue(response.is_error)
        self.assertEqual(response.structured_content["error"]["code"], "public_confirmation_required")
        self.assertEqual(fake.calls, [])

    async def test_publish_parses_the_stable_success_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, source, current, snapshot = make_project(Path(temp))
            fake = FakeRunner(
                command_result(
                    0,
                    stdout="https://artifacts.example/codex/private/report/\n",
                    stderr=(
                        f"read-back: {current}\n"
                        f"snapshot: {snapshot}\n"
                        "published v1 (snapshot: report--1--20260810T120000Z.html)\n"
                    ),
                )
            )
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.publish",
                {
                    "project_path": str(project),
                    "source_path": "report.html",
                    "slug": "report",
                    "tool": "codex",
                    "confirm": True,
                },
            )

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertEqual(result["url"], "https://artifacts.example/codex/private/report/")
        self.assertEqual(result["read_back_path"], str(current.resolve()))
        self.assertEqual(result["snapshot_path"], str(snapshot.resolve()))
        self.assertEqual(result["verification"]["privacy"], "protected")
        argv = fake.calls[0][0]
        self.assertEqual(argv[:6], ("bash", str(ROOT / "skills/artifact-sftp/scripts/publish.sh"), "--slug", "report", "--tool", "codex"))
        self.assertNotIn("--allow-sensitive", argv)
        self.assertNotIn("--force", argv)

    async def test_private_exposure_hides_url_and_raw_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, source, _, _ = make_project(Path(temp))
            fake = FakeRunner(
                command_result(
                    7,
                    stdout="https://leak.invalid/codex/private/report/\n",
                    stderr="ERROR: private URL https://leak.invalid/codex/private/report/ was exposed\n",
                )
            )
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.publish",
                {
                    "project_path": str(project),
                    "source_path": str(source),
                    "slug": "report",
                    "tool": "codex",
                    "confirm": True,
                },
            )

        self.assertTrue(response.is_error)
        payload = response.structured_content
        self.assertEqual(payload["error"]["code"], "private_exposed")
        self.assertTrue(payload["error"]["url_withheld"])
        self.assertNotIn("leak.invalid", response.content[0].text)

    async def test_read_uses_the_real_local_resolver_and_returns_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, current, _ = make_project(Path(temp))
            server = build_server(ArtifactSftpService(plugin_root=ROOT, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.read",
                {
                    "project_path": str(project),
                    "reference": "https://artifacts.example/codex/private/report/",
                    "max_bytes": 8,
                },
            )

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertEqual(result["archive_path"], str(current.resolve()))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["next_cursor"], 8)
        self.assertFalse(result["network_accessed"])
        self.assertTrue(result["content_is_untrusted"])

    async def test_setup_reports_not_ready_without_exposing_a_direct_shell_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            not_ready = command_result(
                3,
                stdout=(
                    "artifact-sftp setup status\n"
                    "CF_ACCESS_CLIENT_SECRET=should-not-escape\n"
                    "config: missing\n"
                    "NOT READY (1 issue(s))\n"
                ),
            )
            fake = FakeRunner(not_ready, not_ready)
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            status = await self.call(server, "artifact_sftp.setup_status", {})
            setup = await self.call(server, "artifact_sftp.setup", {})

        self.assertFalse(status.is_error)
        status_result = status.structured_content["result"]
        self.assertFalse(status_result["ready"])
        self.assertEqual(status_result["agent_action"], "stop")
        self.assertTrue(status_result["configuration_required"])
        self.assertNotIn("next_action", status_result)
        self.assertNotIn("terminal_required", status_result)
        setup_result = setup.structured_content["result"]
        self.assertEqual(setup_result["mode"], "configuration_required")
        self.assertEqual(setup_result["agent_action"], "stop")
        self.assertNotIn("command", setup_result)
        self.assertIn("never receives or relays", setup_result["credential_boundary"])
        self.assertIn("Do not execute a direct setup script", setup_result["configuration_boundary"])
        diagnostics = status.structured_content["result"]["diagnostics"]
        self.assertIn("CF_ACCESS_CLIENT_SECRET=<redacted>", diagnostics)
        self.assertNotIn("should-not-escape", "\n".join(diagnostics))

    async def test_setup_status_structures_fresh_machine_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            not_ready = command_result(
                3,
                stdout=(
                    "artifact-sftp setup status\n"
                    "dependency: python3-paramiko missing\n"
                    "config: missing\n"
                    "config key: SFTP_HOST missing or duplicated\n"
                    "auth: invalid (0 methods configured)\n"
                    "known_hosts: missing or empty\n"
                    "SFTP_PASS=fixture-password-must-not-escape\n"
                    "NOT READY (5 issue(s))\n"
                ),
            )
            fake = FakeRunner(not_ready)
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(server, "artifact_sftp.setup_status", {})

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertEqual(result["status"], "not_ready")
        self.assertFalse(result["ready"])
        self.assertFalse(result["remote_connection_checked"])
        self.assertEqual(result["prerequisites"]["runtime"]["status"], "missing")
        self.assertEqual(result["prerequisites"]["config"]["status"], "missing")
        self.assertEqual(result["prerequisites"]["connection"]["status"], "missing")
        missing = result["missing_prerequisites"]
        self.assertEqual(
            {item["category"] for item in missing},
            {"runtime", "config", "connection"},
        )
        self.assertTrue(any(item["code"] == "dependency_missing" for item in missing))
        self.assertNotIn("fixture-password-must-not-escape", str(result))

    async def test_setup_status_marks_local_prerequisites_ready_without_claiming_remote_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            ready = command_result(
                0,
                stdout=(
                    "artifact-sftp setup status\n"
                    "config directory: present (mode 700)\n"
                    "config: present (mode 600)\n"
                    "auth: ssh-key\n"
                    "default tool: codex\n"
                    "known_hosts: present (mode 600)\n"
                    "READY\n"
                ),
            )
            fake = FakeRunner(ready)
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(server, "artifact_sftp.setup_status", {})

        result = response.structured_content["result"]
        self.assertFalse(response.is_error)
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["missing_prerequisites"], [])
        self.assertTrue(all(check["ready"] for check in result["prerequisites"].values()))
        self.assertFalse(result["remote_connection_checked"])

    async def test_setup_status_can_verify_remote_connection_without_raw_transport_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            local_ready = command_result(
                0,
                stdout=(
                    "artifact-sftp setup status\n"
                    "config directory: present (mode 700)\n"
                    "config: present (mode 600)\n"
                    "auth: ssh-key\n"
                    "default tool: codex\n"
                    "known_hosts: present (mode 600)\n"
                    "READY\n"
                ),
            )
            remote_failure = command_result(
                5,
                stderr="sftp: connection refused for artifact@example.invalid\n",
            )
            fake = FakeRunner(local_ready, remote_failure)
            service = ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project)
            response = service.setup_status(verify_connection=True)

        self.assertFalse(response.is_error)
        result = response.output.result
        self.assertTrue(result["local_ready"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["configuration_required"])
        self.assertTrue(result["remote_connection_checked"])
        self.assertEqual(result["remote_connection"]["status"], "failed")
        self.assertEqual(
            result["remote_connection"]["code"],
            "remote_connection_failed",
        )
        self.assertEqual(result["prerequisites"]["connection"]["status"], "failed")
        self.assertTrue(
            any(item["code"] == "remote_connection_failed" for item in result["missing_prerequisites"])
        )
        self.assertNotIn("example.invalid", str(result))
        self.assertEqual(
            fake.calls[1][0],
            ("bash", str(ROOT / "skills/artifact-sftp/scripts/publish.sh"), "--list", "--tool", "codex"),
        )

    async def test_remote_preflight_does_not_run_when_local_setup_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            local_not_ready = command_result(
                3,
                stdout="config: missing\nknown_hosts: missing or empty\nNOT READY (2 issue(s))\n",
            )
            fake = FakeRunner(local_not_ready)
            service = ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project)
            response = service.setup_status(verify_connection=True)

        self.assertFalse(response.is_error)
        result = response.output.result
        self.assertFalse(result["local_ready"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["remote_connection_checked"])
        self.assertEqual(result["remote_connection"]["status"], "not_run")
        self.assertEqual(len(fake.calls), 1)

    async def test_setup_connection_preflight_success_is_explicitly_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            local_ready = command_result(
                0,
                stdout=(
                    "artifact-sftp setup status\n"
                    "config: present (mode 600)\n"
                    "auth: ssh-key\n"
                    "default tool: codex\n"
                    "known_hosts: present (mode 600)\n"
                    "READY\n"
                ),
            )
            remote_ready = command_result(0, stdout="private/report\npublic/other\n")
            fake = FakeRunner(local_ready, remote_ready)
            service = ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project)
            response = service.setup_instructions(verify_connection=True)

        self.assertFalse(response.is_error)
        result = response.output.result
        self.assertEqual(result["mode"], "ready")
        self.assertTrue(result["setup_status"]["ready"])
        self.assertEqual(
            result["setup_status"]["remote_connection"]["operation"],
            "authenticated_sftp_preflight",
        )
        self.assertNotIn("private/report", str(result))

    async def test_setup_status_connection_preflight_is_available_through_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            local_ready = command_result(
                0,
                stdout=(
                    "artifact-sftp setup status\n"
                    "config: present (mode 600)\n"
                    "auth: ssh-key\n"
                    "default tool: codex\n"
                    "known_hosts: present (mode 600)\n"
                    "READY\n"
                ),
            )
            remote_ready = command_result(0, stdout="remote entries are intentionally discarded\n")
            fake = FakeRunner(local_ready, remote_ready)
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.setup_status",
                {"verify_connection": True},
            )

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertTrue(result["ready"])
        self.assertEqual(result["remote_connection"]["status"], "verified")
        self.assertTrue(result["remote_connection_checked"])
        self.assertNotIn("remote entries", str(result))

    async def test_setup_status_classifies_invalid_public_base_url_in_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            local_not_ready = command_result(
                3,
                stdout=(
                    "artifact-sftp setup status\n"
                    "config: present (mode 600)\n"
                    "config: PUBLIC_BASE_URL is invalid (must be an HTTPS origin with a host, no path/query/fragment, and no trailing slash)\n"
                    "auth: ssh-key\n"
                    "default tool: codex\n"
                    "known_hosts: present (mode 600)\n"
                    "NOT READY: 1 issue(s) found\n"
                ),
            )
            fake = FakeRunner(local_not_ready)
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(server, "artifact_sftp.setup_status", {})

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertFalse(result["ready"])
        self.assertFalse(result["local_ready"])
        self.assertFalse(result["prerequisites"]["config"]["ready"])
        self.assertEqual(result["missing_prerequisites"][0]["category"], "config")
        self.assertEqual(result["missing_prerequisites"][0]["code"], "config_invalid")

    async def test_unpublish_requires_confirmation_without_starting_a_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            fake = FakeRunner()
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.unpublish",
                {
                    "project_path": str(project),
                    "slug": "report",
                    "tool": "codex",
                },
            )

        self.assertTrue(response.is_error)
        self.assertEqual(response.structured_content["error"]["code"], "confirmation_required")
        self.assertEqual(fake.calls, [])

    async def test_public_unpublish_requires_its_own_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            fake = FakeRunner()
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.unpublish",
                {
                    "project_path": str(project),
                    "slug": "report",
                    "tool": "codex",
                    "visibility": "public",
                    "confirm": True,
                },
            )

        self.assertTrue(response.is_error)
        self.assertEqual(
            response.structured_content["error"]["code"],
            "public_confirmation_required",
        )
        self.assertEqual(fake.calls, [])

    async def test_unpublish_dry_run_passes_dry_run_to_publisher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            fake = FakeRunner(command_result(0, stdout="dry-run: would delete codex/private/report\n"))
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.unpublish",
                {
                    "project_path": str(project),
                    "slug": "report",
                    "tool": "codex",
                    "dry_run": True,
                },
            )

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["remote_removed"])
        self.assertTrue(result["local_archive_retained"])
        self.assertEqual(len(fake.calls), 1)
        argv, cwd, timeout = fake.calls[0]
        self.assertIn("--delete", argv)
        self.assertIn("--dry-run", argv)

    async def test_unpublish_succeeds_and_preserves_local_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, current, _ = make_project(Path(temp))
            fake = FakeRunner(command_result(0, stderr="deleted: codex/private/report\n"))
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=fake, start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.unpublish",
                {
                    "project_path": str(project),
                    "slug": "report",
                    "tool": "codex",
                    "confirm": True,
                },
            )

            self.assertFalse(response.is_error)
            result = response.structured_content["result"]
            self.assertEqual(result["status"], "unpublished")
            self.assertFalse(result["dry_run"])
            self.assertTrue(result["remote_removed"])
            self.assertTrue(result["local_archive_retained"])
            # Local archive files must remain untouched
            self.assertTrue(current.is_file())

    async def test_list_inventory_discovers_artifacts_and_local_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, source, current, snapshot = make_project(Path(temp))
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=FakeRunner(), start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.list",
                {"project_path": str(project)},
            )

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertEqual(result["artifacts_count"], 1)
        self.assertEqual(len(result["artifacts"]), 1)
        item = result["artifacts"][0]
        self.assertEqual(item["tool"], "codex")
        self.assertEqual(item["visibility"], "private")
        self.assertEqual(item["slug"], "report")
        self.assertEqual(item["latest_version"], 1)
        self.assertEqual(item["snapshot_count"], 1)
        self.assertTrue(item["index_present"])
        self.assertIn("report.html", result["local_drafts"])

    async def test_list_inventory_filters_by_tool_and_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, _, _, _ = make_project(Path(temp))
            server = build_server(ArtifactSftpService(plugin_root=ROOT, runner=FakeRunner(), start_cwd=project))
            response = await self.call(
                server,
                "artifact_sftp.list",
                {"project_path": str(project), "tool": "openclaw", "visibility": "public"},
            )

        self.assertFalse(response.is_error)
        result = response.structured_content["result"]
        self.assertEqual(result["artifacts_count"], 0)
        self.assertEqual(result["artifacts"], [])


if __name__ == "__main__":
    unittest.main()
