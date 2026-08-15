#!/usr/bin/env python3
"""Fresh-machine launch failures must be short, safe, and distinguishable.

These cases happen before the MCP server can answer ``setup_status``.  Test
the packaged launcher directly so an installer does not turn every failure
into the unhelpful generic "cannot connect" message.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin/artifact-sftp-mcp"


class ArtifactSftpMcpLauncherTests(unittest.TestCase):
    def run_launcher(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = {"PATH": os.defpath}
        environment.update(overrides)
        return subprocess.run(
            (str(LAUNCHER),),
            cwd=ROOT,
            env=environment,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )

    def assert_startup_boundary(
        self, result: subprocess.CompletedProcess[str], expected: str
    ) -> None:
        self.assertEqual(result.returncode, 78, result.stderr)
        self.assertEqual(result.stdout, "", "stdio stdout must remain clean")
        self.assertIn(expected, result.stderr)

    def test_rejects_an_untrusted_plugin_root_before_trying_to_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_launcher(
                PLUGIN_ROOT=temporary,
                PLUGIN_DATA=str(Path(temporary) / "plugin-data"),
            )

        self.assert_startup_boundary(result, "trusted plugin root is unavailable")

    def test_requires_the_portable_plugin_root_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_launcher(PLUGIN_DATA=str(Path(temporary) / "plugin-data"))

        self.assert_startup_boundary(result, "plugin host did not provide PLUGIN_ROOT")

    def test_requires_host_supplied_plugin_data(self) -> None:
        result = self.run_launcher(PLUGIN_ROOT=str(ROOT))

        self.assert_startup_boundary(result, "plugin host did not provide PLUGIN_DATA")

    def test_rejects_an_unwritable_plugin_data_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plugin_data_file = Path(temporary) / "not-a-directory"
            plugin_data_file.write_text("not writable as a directory", encoding="utf-8")
            result = self.run_launcher(
                PLUGIN_ROOT=str(ROOT),
                PLUGIN_DATA=str(plugin_data_file),
            )

        self.assert_startup_boundary(result, "PLUGIN_DATA that is not writable")

    def test_requires_uv_on_the_actual_mcp_child_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_launcher(
                PLUGIN_ROOT=str(ROOT),
                PLUGIN_DATA=str(Path(temporary) / "plugin-data"),
            )

        self.assert_startup_boundary(result, "MCP owner must pre-provision uv on PATH")


if __name__ == "__main__":
    unittest.main()
