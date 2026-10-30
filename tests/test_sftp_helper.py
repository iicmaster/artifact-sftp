"""Offline unit tests for skills/artifact-sftp/scripts/sftp_helper.py.

Pins the exit contract the publisher's overwrite guard depends on:

    0 ok | 1 confirmed remote ENOENT (exists/get only) | 2 usage
    | 4 every other failure | 10 outside the MCP adapter

Exit 1 must be impossible for anything that is not a REMOTE no-such-file
answer: a missing local config, a missing pinned known_hosts, DNS, connection,
auth, host-key mismatch, server refusals (IOError("Failure"), errno None),
protocol garbage (EOFError / plain-Exception SFTPError) and uncaught exceptions
all have to land on 4 — otherwise a transport failure reads as "the slug is
absent" and publish skips the custody check (gap G17).

The fakes use paramiko 5.0's real constructor shapes: IOError(errno.ENOENT, t)
IS a FileNotFoundError, IOError(errno.EACCES, t) a PermissionError, and server
refusals arrive as IOError("Failure") with errno None.
"""

import contextlib
import errno
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "artifact-sftp", "scripts", "sftp_helper.py")


def load_helper():
    spec = importlib.util.spec_from_file_location("sftp_helper_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unlink_quiet(path):
    with contextlib.suppress(OSError):
        os.unlink(path)


class FakeSSHException(Exception):
    """Stand-in for paramiko.SSHException (a plain Exception, not an OSError)."""


class FakeSFTP:
    def __init__(self, stat_exc=None, listdir_exc=None, stat_map=None, listing=None):
        self.stat_exc = stat_exc
        self.listdir_exc = listdir_exc
        self.stat_map = stat_map if stat_map is not None else {}
        self.listing = listing if listing is not None else []

    def stat(self, path):
        if self.stat_exc is not None:
            raise self.stat_exc
        if path in self.stat_map:
            return self.stat_map[path]
        raise IOError(errno.ENOENT, "No such file or directory")

    def listdir(self, path):
        if self.listdir_exc is not None:
            raise self.listdir_exc
        return list(self.listing)

    def put(self, local, remote):
        pass

    def remove(self, path):
        raise IOError(errno.ENOENT, "No such file or directory")  # first publish

    def rename(self, a, b):
        pass

    def chmod(self, path, mode):
        pass

    def mkdir(self, path):
        pass

    def rmdir(self, path):
        pass

    def get(self, rfile, lfile):
        pass


class FakeTransport:
    def __init__(self, *args):
        self.closed = False

    def start_client(self, timeout=None):
        pass

    def get_remote_server_key(self):
        return object()

    def auth_password(self, user, password):
        pass

    def close(self):
        self.closed = True


class HelperContractTests(unittest.TestCase):
    """Per-op classification with connect() faked (taxonomy per paramiko 5.0)."""

    def setUp(self):
        self.helper = load_helper()
        fd, self.cfg_path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write("SFTP_HOST=h.example\nSFTP_USER=u\nSFTP_PASS=p\n")
        cfg = mock.patch.object(self.helper, "CONFIG", self.cfg_path)
        cfg.start()
        self.addCleanup(cfg.stop)
        env = mock.patch.dict(os.environ, {"ARTIFACT_SFTP_MCP_CALL": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.transport = FakeTransport()
        self.sftp = FakeSFTP()
        conn = mock.patch.object(
            self.helper, "connect", return_value=(self.transport, self.sftp)
        )
        conn.start()
        self.addCleanup(conn.stop)
        self.addCleanup(_unlink_quiet, self.cfg_path)

    def run_op(self, argv, stdout=None):
        ctx = contextlib.redirect_stdout(stdout if stdout is not None else io.StringIO())
        with ctx, mock.patch.object(sys, "argv", ["sftp_helper.py"] + argv):
            self.helper.main()

    def assert_exit(self, argv, code):
        with self.assertRaises(SystemExit) as ctx:
            self.run_op(argv)
        # A str code would become interpreter status 1 — the "absent" code.
        self.assertIsInstance(ctx.exception.code, int, ctx.exception.code)
        self.assertEqual(ctx.exception.code, code)

    # ---- exists: 1 is reserved for a confirmed remote ENOENT ----

    def test_exists_remote_enoent_is_file_not_found_and_exits_1(self):
        exc = IOError(errno.ENOENT, "No such file or directory")
        self.assertIsInstance(exc, FileNotFoundError)  # pin paramiko's mapping
        self.sftp.stat_exc = exc
        self.assert_exit(["exists", "/tool/private/slug"], 1)

    def test_exists_string_only_enoent_falls_back_to_1(self):
        self.sftp.stat_exc = IOError("No such file or directory")  # errno None
        self.assert_exit(["exists", "/tool/private/slug"], 1)

    def test_exists_permission_denied_exits_4(self):
        exc = IOError(errno.EACCES, "Permission denied")
        self.assertIsInstance(exc, PermissionError)
        self.sftp.stat_exc = exc
        self.assert_exit(["exists", "/tool/private/slug"], 4)

    def test_exists_server_refusal_errno_none_exits_4(self):
        self.sftp.stat_exc = IOError("Failure")
        self.assert_exit(["exists", "/tool/private/slug"], 4)

    def test_exists_eoferror_exits_4(self):
        self.sftp.stat_exc = EOFError()
        self.assert_exit(["exists", "/tool/private/slug"], 4)

    def test_exists_ssh_exception_exits_4(self):
        self.sftp.stat_exc = FakeSSHException("Server connection dropped")
        self.assert_exit(["exists", "/tool/private/slug"], 4)

    def test_exists_ok_exits_cleanly_and_closes_transport(self):
        self.sftp.stat_map = {"/tool/private/slug/index.html": object()}
        out = io.StringIO()
        self.run_op(["exists", "/tool/private/slug"], stdout=out)
        self.assertTrue(self.transport.closed)  # finally ran even without SystemExit

    # ---- versions: ENOENT is an empty success; nothing else may be ----

    def test_versions_enoent_is_empty_success(self):
        self.sftp.listdir_exc = IOError(errno.ENOENT, "No such file or directory")
        out = io.StringIO()
        self.run_op(["versions", "/tool/private/slug"], stdout=out)
        self.assertEqual(out.getvalue(), "")

    def test_versions_failure_exits_4(self):
        self.sftp.listdir_exc = IOError("Failure")
        self.assert_exit(["versions", "/tool/private/slug"], 4)

    def test_versions_transport_death_exits_4(self):
        self.sftp.listdir_exc = FakeSSHException("Server connection dropped")
        self.assert_exit(["versions", "/tool/private/slug"], 4)

    def test_versions_prints_sorted_listing(self):
        self.sftp.listing = ["b.html", "a.html"]
        out = io.StringIO()
        self.run_op(["versions", "/tool/private/slug"], stdout=out)
        self.assertEqual(out.getvalue(), "a.html\nb.html\n")

    # ---- get: remote-only probe before the transfer (read-artifact.sh maps 1 to not-found) ----

    def test_get_remote_enoent_exits_1(self):
        self.assert_exit(["get", "/tool/private/slug/index.html", "/tmp/x"], 1)

    def test_get_remote_refusal_exits_4(self):
        self.sftp.stat_exc = IOError("Failure")
        self.assert_exit(["get", "/tool/private/slug/index.html", "/tmp/x"], 4)

    def test_get_local_write_error_is_not_not_found(self):
        self.sftp.stat_map = {"/remote/index.html": object()}
        self.sftp.get = lambda r, l: (_ for _ in ()).throw(PermissionError("local disk"))
        # In-process this must NOT surface as SystemExit(1); the __main__ guard
        # maps it to 4 at interpreter level (pinned by the subprocess tests).
        with self.assertRaises(PermissionError):
            self.run_op(["get", "/remote/index.html", "/tmp/x"])

    # ---- list: a missing visibility dir is skippable; a failure is not ----

    def test_list_missing_visibility_dirs_are_skipped(self):
        self.sftp.listdir_exc = IOError(errno.ENOENT, "No such file or directory")
        out = io.StringIO()
        self.run_op(["list", "/tool"], stdout=out)
        self.assertEqual(out.getvalue(), "")

    def test_list_failure_exits_4(self):
        self.sftp.listdir_exc = FakeSSHException("Server connection dropped")
        self.assert_exit(["list", "/tool"], 4)

    def test_list_prints_visibility_prefixed_names(self):
        self.sftp.listing = ["slug"]
        out = io.StringIO()
        self.run_op(["list", "/tool"], stdout=out)
        self.assertEqual(out.getvalue(), "private/slug\npublic/slug\n")

    # ---- delete: ENOENT is idempotent success; failures surface ----

    def test_delete_enoent_is_idempotent_success(self):
        self.sftp.listdir_exc = IOError(errno.ENOENT, "No such file or directory")
        self.run_op(["delete", "/tool/private/slug"])  # no SystemExit

    def test_delete_failure_exits_4(self):
        self.sftp.listdir_exc = IOError(errno.EACCES, "Permission denied")
        self.assert_exit(["delete", "/tool/private/slug"], 4)

    # ---- upload: chmod stays best-effort AFTER the artifact is live ----

    def test_upload_chmod_failure_is_tolerated(self):
        self.sftp.stat_map = {"": object()}  # mkdirs: root stat ok
        self.sftp.chmod = lambda p, m: (_ for _ in ()).throw(FakeSSHException("chmod refused"))
        self.run_op(["upload", __file__, "/tool/private/slug", "slug--1--x.html"])

    def test_upload_live_index_remove_absent_is_normal_first_publish(self):
        self.sftp.stat_map = {"": object()}
        self.run_op(["upload", __file__, "/tool/private/slug", "slug--1--x.html"])

    # ---- usage / unknown op / guard ----

    def test_usage_exits_2(self):
        self.assert_exit([], 2)

    def test_unknown_op_exits_2(self):
        self.assert_exit("frobnicate /x".split(), 2)

    def test_outside_mcp_exits_10(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            del os.environ["ARTIFACT_SFTP_MCP_CALL"]
            self.assert_exit(["exists", "/x"], 10)


class ConnectContractTests(unittest.TestCase):
    """connect() itself: the worst exit-1 leaks lived here."""

    def setUp(self):
        self.helper = load_helper()
        fd, self.cfg_path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write("SFTP_HOST=h.example\nSFTP_USER=u\nSFTP_PASS=p\nSFTP_PORT=2222\n")
        cfg = mock.patch.object(self.helper, "CONFIG", self.cfg_path)
        cfg.start()
        self.addCleanup(cfg.stop)
        env = mock.patch.dict(os.environ, {"ARTIFACT_SFTP_MCP_CALL": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(_unlink_quiet, self.cfg_path)

    def fake_paramiko(self, transport_cls=None, host_check=None):
        if transport_cls is None:
            transport_cls = FakeTransport
        module = types.ModuleType("paramiko")

        class _HostKeys:
            def __init__(self, path):
                pass

            def check(self, lookup, key):
                return False if host_check == "mismatch" else True

        module.hostkeys = types.SimpleNamespace(HostKeys=_HostKeys)
        module.Transport = transport_cls
        module.SFTPClient = types.SimpleNamespace(
            from_transport=lambda t: FakeSFTP(stat_map={"": object()})
        )
        return module

    def run_connect_case(self, argv, fake_module):
        with mock.patch.dict(sys.modules, {"paramiko": fake_module}):
            with mock.patch.object(sys, "argv", ["sftp_helper.py"] + argv):
                with self.assertRaises(SystemExit) as ctx:
                    self.helper.main()
        return ctx.exception.code

    def test_host_key_mismatch_exits_4_not_1(self):
        code = self.run_connect_case(
            ["exists", "/x"], self.fake_paramiko(host_check="mismatch")
        )
        self.assertIsInstance(code, int)
        self.assertEqual(code, 4)

    def test_dns_failure_exits_4(self):
        class _Dead(FakeTransport):
            def __init__(self, addr):
                raise OSError("name or service not known")

        code = self.run_connect_case(["exists", "/x"], self.fake_paramiko(_Dead))
        self.assertEqual(code, 4)

    def test_auth_failure_exits_4(self):
        class _AuthFail(FakeTransport):
            def auth_password(self, user, password):
                raise FakeSSHException("Authentication failed.")

        code = self.run_connect_case(["exists", "/x"], self.fake_paramiko(_AuthFail))
        self.assertEqual(code, 4)

    def test_missing_sftp_subsystem_exits_4(self):
        module = self.fake_paramiko()
        module.SFTPClient = types.SimpleNamespace(from_transport=lambda t: None)
        code = self.run_connect_case(["exists", "/x"], module)
        self.assertEqual(code, 4)


class SubprocessContractTests(unittest.TestCase):
    """Interpreter-level status: the guard at __main__ is what makes exit 1 rare."""

    def run_script(self, *argv, **env_over):
        env = {k: v for k, v in os.environ.items() if k != "ARTIFACT_SFTP_MCP_CALL"}
        env.update(env_over)
        return subprocess.run(
            [sys.executable, SCRIPT, *argv],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def test_outside_mcp_exits_10(self):
        proc = self.run_script("exists", "/x")
        self.assertEqual(proc.returncode, 10)

    def test_missing_config_exits_4_not_1(self):
        # A missing local config is a LOCAL failure. Before the G17 fix this
        # escaped as an unhandled FileNotFoundError -> status 1, which publish.sh
        # read as "the slug is genuinely absent".
        with tempfile.TemporaryDirectory() as home:
            proc = self.run_script(
                "exists", "/x", HOME=home, ARTIFACT_SFTP_MCP_CALL="1"
            )
        self.assertEqual(proc.returncode, 4, proc.stderr)

    def test_usage_exits_2_at_interpreter_level(self):
        with tempfile.TemporaryDirectory() as home:
            proc = self.run_script(HOME=home, ARTIFACT_SFTP_MCP_CALL="1")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
