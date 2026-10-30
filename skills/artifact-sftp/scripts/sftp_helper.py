#!/usr/bin/env python3
"""paramiko transport for publish.sh when the SFTP account is password-auth.

Used only when SFTP_PASS is set in the config. Reads the fixed config path itself,
so the password never crosses argv or the environment. Host key is verified against
the same pinned known_hosts file the OpenSSH path uses.

ops: exists RPATH | upload LOCAL RPATH [VERSIONED_NAME] | delete RPATH | list RBASE
      | versions RPATH | get RFILE LFILE
Exit: 0 ok | 1 remote path confirmed absent (exists/get only) | 2 usage
      | 4 refused/failed (messages on stderr) | 10 outside the MCP adapter

Exit 1 is reserved for a CONFIRMED remote ENOENT — the caller's overwrite guard
depends on that distinction (same contract as s3_helper.py). Every other failure —
a missing local config, a missing pinned known_hosts, DNS, connection, auth, host
key mismatch, a server refusal, an unexpected exception — exits 4, so a failure can
never be mistaken for a missing slug. Note: start_client(timeout=15) bounds SSH
negotiation only; the TCP connect itself is bounded by the caller's timeout.
"""
import contextlib
import errno
import os
import sys

CONFIG = os.path.expanduser("~/.config/artifact-sftp/config")

EXIT_USAGE = 2
EXIT_FAILED = 4


def require_mcp_call():
    """Keep this transport internal to the Artifact SFTP MCP adapter."""

    if os.environ.get("ARTIFACT_SFTP_MCP_CALL") != "1":
        print(
            "sftp_helper.py is internal to Artifact SFTP MCP; AI agents must use artifact_sftp.* tools.",
            file=sys.stderr,
        )
        raise SystemExit(10)


def _fail(message, code=EXIT_FAILED):
    """Report on stderr and exit with an int code (s3_helper.py idiom).

    The stderr write is guarded: a closed stderr must not turn the exit code into
    an unhandled traceback, whose interpreter status (1) would read as "absent".
    """
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass
    raise SystemExit(code)


def _remote_enoent(e):
    """True only for a REMOTE 'no such file' answer.

    Apply at remote SFTP call sites ONLY: local OSErrors (the config read, the
    pinned known_hosts load, local file opens inside put/get) share the errno
    space, so wrapping anything but a remote call in this predicate can turn a
    local failure into "remote absent". paramiko maps SSH_FX_NO_SUCH_FILE to
    IOError(errno.ENOENT, ...) and every other status to a DIFFERENT errno or to
    IOError(text) with errno None — so a present errno is authoritative and must
    never be overridden by message text (a server may word a permission denial
    "No such file or directory"); the string fallback applies only when the
    server sent no code at all.
    """
    if not isinstance(e, OSError):
        return False
    if e.errno is not None:
        return e.errno == errno.ENOENT
    return "No such file" in str(e)


def read_cfg():
    cfg = {}
    with open(CONFIG) as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            # The value is kept byte-for-byte. A password may legitimately start or end
            # with a space, and stripping it here would silently authenticate with the
            # wrong secret.
            cfg[k.strip()] = v
    return cfg


def connect(cfg):
    import paramiko

    host = cfg["SFTP_HOST"]
    port = int(cfg.get("SFTP_PORT", "22"))
    kh_path = os.path.expanduser(
        cfg.get("KNOWN_HOSTS", "~/.config/artifact-sftp/known_hosts")
    )
    t = None
    try:
        # A missing/unreadable pinned known_hosts is a LOCAL failure: it reaches the
        # handler below and exits 4, never the "absent" code 1.
        hostkeys = paramiko.hostkeys.HostKeys(kh_path)
        t = paramiko.Transport((host, port))  # DNS + TCP: gaierror / SSHException
        t.start_client(timeout=15)
        key = t.get_remote_server_key()
        lookup = host if port == 22 else f"[{host}]:{port}"
        if not hostkeys.check(lookup, key):
            _fail(f"host key verification failed (pinned known_hosts mismatch) host={lookup}")
        t.auth_password(cfg["SFTP_USER"], cfg["SFTP_PASS"])
        sftp = paramiko.SFTPClient.from_transport(t)
        if sftp is None:
            _fail("could not open the SFTP subsystem on the server")
        return t, sftp
    except SystemExit:
        with contextlib.suppress(Exception):
            if t is not None:
                t.close()
        raise
    except Exception as e:  # gaierror, SSHException, AuthenticationException, EOFError, ...
        with contextlib.suppress(Exception):
            if t is not None:
                t.close()
        _fail(f"connect/auth failed ({host}:{port}): {e!r}")


def mkdirs(sftp, path):
    cur = ""
    for part in [p for p in path.split("/") if p]:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except Exception as e:
            if not _remote_enoent(e):
                raise  # e.g. permission denied: creating it would fail anyway — surface it
            sftp.mkdir(cur)  # lost create race -> server "Failure" -> global guard -> exit 4


def main():
    require_mcp_call()
    if len(sys.argv) < 3:
        _fail("usage: sftp_helper.py exists|upload|delete|list|versions|get ARGS", EXIT_USAGE)
    op = sys.argv[1]
    cfg = read_cfg()
    t, sftp = connect(cfg)
    try:
        if op == "exists":
            try:
                sftp.stat(sys.argv[2] + "/index.html")
            except Exception as e:
                if _remote_enoent(e):
                    raise SystemExit(1)  # confirmed: no live artifact at this path
                _fail(f"exists failed for {sys.argv[2]!r}: {e!r}")
        elif op == "upload":
            local, rpath = sys.argv[2], sys.argv[3]
            vname = sys.argv[4] if len(sys.argv) > 4 else None
            mkdirs(sftp, rpath)
            tmp, final = rpath + "/index.html.tmp", rpath + "/index.html"
            sftp.put(local, tmp)
            try:
                sftp.remove(final)
            except Exception as e:
                if not _remote_enoent(e):
                    raise  # first publish has no live index to remove; anything else must surface
            sftp.rename(tmp, final)
            targets = [final]
            if vname:
                sftp.put(local, rpath + "/" + vname)
                targets.append(rpath + "/" + vname)
            for tgt in targets:  # NOT `t` — that would shadow the Transport closed in finally
                try:
                    sftp.chmod(tgt, 0o644)
                except Exception:
                    pass  # some servers reject chmod; upload already live — never fail after it
        elif op == "delete":
            rpath = sys.argv[2]
            try:
                names = sftp.listdir(rpath)
            except Exception as e:
                # If the directory does not exist, consider it already deleted (idempotent).
                if not _remote_enoent(e):
                    _fail(f"delete failed for {rpath!r}: {e!r}")
            else:
                for name in names:
                    try:
                        sftp.remove(rpath + "/" + name)
                    except Exception as e:
                        if not _remote_enoent(e):
                            _fail(f"delete failed for {rpath}/{name}: {e!r}")
                try:
                    sftp.rmdir(rpath)
                except Exception as e:
                    if not _remote_enoent(e):
                        _fail(f"delete failed for {rpath!r}: {e!r}")
        elif op == "versions":
            try:
                names = sorted(sftp.listdir(sys.argv[2]))  # materialize before printing
            except Exception as e:
                if _remote_enoent(e):
                    names = []  # slug dir doesn't exist yet -> no versions, not a failure
                else:
                    _fail(f"versions failed for {sys.argv[2]!r}: {e!r}")
            for name in names:
                print(name)
        elif op == "get":
            rfile, lfile = sys.argv[2], sys.argv[3]
            try:
                sftp.stat(rfile)  # remote-only probe: local errors are impossible here
            except Exception as e:
                if _remote_enoent(e):
                    raise SystemExit(1)  # genuinely absent — read-artifact.sh maps 1 to not-found
                _fail(f"get failed for {rfile!r}: {e!r}")
            sftp.get(rfile, lfile)  # a local write error -> global guard -> exit 4
        elif op == "list":
            base = sys.argv[2]
            for vis in ("private", "public"):
                try:
                    names = sorted(sftp.listdir(f"{base}/{vis}"))
                except Exception as e:
                    if _remote_enoent(e):
                        continue  # visibility dir not created yet on a fresh host
                    _fail(f"list failed for {base}/{vis}: {e!r}")
                for name in names:
                    print(f"{vis}/{name}")
        else:
            _fail(f"unknown op: {op}", EXIT_USAGE)
    finally:
        with contextlib.suppress(Exception):
            t.close()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # nothing may exit 1 by accident — 1 means "confirmed absent"
        _fail(f"sftp_helper failed: {e!r}")
