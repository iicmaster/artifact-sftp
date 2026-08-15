#!/usr/bin/env python3
"""The child environment the adapter hands to the bundled scripts.

These run the real ``SubprocessRunner`` against a real script, because the
defect being guarded here was invisible to every unit: the helper that chooses
PATH was correct in isolation, and the scripts were correct in isolation.  Only
the pair was wrong, and only when launched the documented way.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from artifact_sftp_mcp import service as service_module  # noqa: E402
from artifact_sftp_mcp.service import SubprocessRunner  # noqa: E402


def echo_path_script(base: Path) -> Path:
    script = base / "echo-path.sh"
    script.write_text('#!/bin/sh\nprintf "%s" "$PATH"\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


class ChildPathTest(unittest.TestCase):
    def test_the_adapters_own_venv_never_reaches_a_script(self) -> None:
        # The failure this reproduces: uv run prepends the adapter's venv, the
        # scripts resolve python3 from PATH, and setup.sh reports the host NOT
        # READY while the same script run from a shell reports READY.
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            venv_bin = base / "venv" / "bin"
            venv_bin.mkdir(parents=True)
            keeper = base / "real-tools"
            keeper.mkdir()
            script = echo_path_script(base)

            poisoned = os.pathsep.join([str(venv_bin), str(keeper), os.defpath])
            with mock.patch.dict(
                os.environ, {"VIRTUAL_ENV": str(base / "venv"), "PATH": poisoned}
            ):
                result = SubprocessRunner().run([str(script)], cwd=base, timeout=30)

        self.assertEqual(result.returncode, 0, result.stderr)
        delivered = result.stdout.split(os.pathsep)
        self.assertNotIn(str(venv_bin), delivered)
        # and it removed only that: a PATH stripped down to nothing would hide
        # this bug behind a much louder one.
        self.assertIn(str(keeper), delivered)

    def test_outside_a_venv_the_path_is_handed_over_untouched(self) -> None:
        # sys.prefix is the base install when nothing is activated, and its bin
        # is where the system tools live.  Dropping it would be worse than the
        # defect above, so the guard is asserted rather than assumed.
        original = os.pathsep.join(["/usr/bin", "/bin", "/opt/homebrew/bin"])
        with mock.patch.object(service_module.sys, "prefix", sys.base_prefix), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIRTUAL_ENV", None)
            self.assertEqual(
                SubprocessRunner._path_without_own_runtime(original), original
            )

    def test_a_path_that_is_only_the_venv_falls_back_to_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            venv = Path(raw) / "venv"
            (venv / "bin").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": str(venv)}):
                self.assertEqual(
                    SubprocessRunner._path_without_own_runtime(str(venv / "bin")),
                    os.defpath,
                )


if __name__ == "__main__":
    unittest.main()
