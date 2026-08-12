#!/usr/bin/env python3
"""paramiko transport for publish.sh when the SFTP account is password-auth.

Used only when SFTP_PASS is set in the config. Reads the fixed config path itself,
so the password never crosses argv or the environment. Host key is verified against
the same pinned known_hosts file the OpenSSH path uses.

ops: exists RPATH | upload LOCAL RPATH [VERSIONED_NAME] | delete RPATH | list RBASE | versions RPATH
Exit: 0 ok | 1 not-found/failed (messages on stderr)
"""
import os
import sys

CONFIG = os.path.expanduser("~/.config/artifact-sftp/config")


def require_mcp_call():
    """Keep this transport internal to the Artifact SFTP MCP adapter."""

    if os.environ.get("ARTIFACT_SFTP_MCP_CALL") != "1":
        print(
            "sftp_helper.py is internal to Artifact SFTP MCP; AI agents must use artifact_sftp.* tools.",
            file=sys.stderr,
        )
        raise SystemExit(10)


def read_cfg():
    cfg = {}
    with open(CONFIG) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k] = v
    return cfg


def connect(cfg):
    import paramiko

    host = cfg["SFTP_HOST"]
    port = int(cfg.get("SFTP_PORT", "22"))
    kh_path = os.path.expanduser(
        cfg.get("KNOWN_HOSTS", "~/.config/artifact-sftp/known_hosts")
    )
    hostkeys = paramiko.hostkeys.HostKeys(kh_path)
    t = paramiko.Transport((host, port))
    t.start_client(timeout=15)
    key = t.get_remote_server_key()
    lookup = host if port == 22 else f"[{host}]:{port}"
    if not hostkeys.check(lookup, key):
        sys.exit("host key verification failed (pinned known_hosts mismatch)")
    t.auth_password(cfg["SFTP_USER"], cfg["SFTP_PASS"])
    return t, paramiko.SFTPClient.from_transport(t)


def mkdirs(sftp, path):
    cur = ""
    for part in [p for p in path.split("/") if p]:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


def main():
    require_mcp_call()
    if len(sys.argv) < 3:
        sys.exit("usage: sftp_helper.py exists|upload|delete|list ARGS")
    op = sys.argv[1]
    cfg = read_cfg()
    t, sftp = connect(cfg)
    try:
        if op == "exists":
            try:
                sftp.stat(sys.argv[2] + "/index.html")
            except IOError:
                sys.exit(1)
        elif op == "upload":
            local, rpath = sys.argv[2], sys.argv[3]
            vname = sys.argv[4] if len(sys.argv) > 4 else None
            mkdirs(sftp, rpath)
            tmp, final = rpath + "/index.html.tmp", rpath + "/index.html"
            sftp.put(local, tmp)
            try:
                sftp.remove(final)
            except IOError:
                pass
            sftp.rename(tmp, final)
            targets = [final]
            if vname:
                sftp.put(local, rpath + "/" + vname)
                targets.append(rpath + "/" + vname)
            for tgt in targets:  # NOT `t` — that would shadow the Transport closed in finally
                try:
                    sftp.chmod(tgt, 0o644)
                except IOError:
                    pass  # some servers reject chmod; upload already live
        elif op == "delete":
            rpath = sys.argv[2]
            for name in sftp.listdir(rpath):
                sftp.remove(rpath + "/" + name)
            sftp.rmdir(rpath)
        elif op == "versions":
            try:
                for name in sorted(sftp.listdir(sys.argv[2])):
                    print(name)
            except IOError:
                pass  # slug dir doesn't exist yet -> no versions
        elif op == "list":
            base = sys.argv[2]
            for vis in ("private", "public"):
                try:
                    for name in sorted(sftp.listdir(f"{base}/{vis}")):
                        print(f"{vis}/{name}")
                except IOError:
                    pass
        else:
            sys.exit(f"unknown op: {op}")
    finally:
        t.close()


if __name__ == "__main__":
    main()
