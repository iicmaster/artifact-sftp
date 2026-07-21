#!/usr/bin/env bash
# artifact-sftp setup — pin the SFTP host key and write ~/.config/artifact-sftp/config (0600).
# Flag-driven so an agent can run it non-interactively. The password (if any) is read from
# STDIN, never argv, so it never lands in a process listing or shell history.
#
# usage:
#   setup.sh --host H --user U [--port 22] --remote-dir /files --url https://host [--tool codex]
#            [--basic-auth -] [--cf-access-id ID --cf-access-secret -]
#            ( --pass - | --ssh-key PATH | --op-ref op://... )
#   Secrets are read from stdin, ONE PER LINE, in this fixed order (only the ones you
#   requested with -): SFTP password, basic-auth, cf-access-secret. Example:
#   printf '%s\n%s\n' "$SFTP_PASSWORD" "$BASIC_USER:$BASIC_PASS" | setup.sh ... --pass - --basic-auth -
#   Cloudflare Access service token verifies private artifacts (Zero Trust):
#   printf '%s' "$CF_SECRET" | setup.sh ... --ssh-key K --cf-access-id "$CF_ID" --cf-access-secret -
set -euo pipefail
umask 077

CFG_DIR="$HOME/.config/artifact-sftp"
CONFIG="$CFG_DIR/config"
KNOWN="$CFG_DIR/known_hosts"

err() { printf '%s\n' "$*" >&2; }
die() { err "ERROR: $*"; exit 2; }

HOST='' SUSER='' PORT=22 REMOTE='' URL='' TOOL='' BASIC='' AUTH_MODE='' SSH_KEY='' OP_REF='' READ_PASS=0 READ_BASIC=0
CF_ID='' CF_SECRET='' READ_CFSEC=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host)        [ $# -ge 2 ] || die "--host needs a value"; HOST=$2; shift 2 ;;
    --user)        [ $# -ge 2 ] || die "--user needs a value"; SUSER=$2; shift 2 ;;
    --port)        [ $# -ge 2 ] || die "--port needs a value"; PORT=$2; shift 2 ;;
    --remote-dir)  [ $# -ge 2 ] || die "--remote-dir needs a value"; REMOTE=$2; shift 2 ;;
    --url)         [ $# -ge 2 ] || die "--url needs a value"; URL=$2; shift 2 ;;
    --tool)        [ $# -ge 2 ] || die "--tool needs a value"; TOOL=$2; shift 2 ;;
    --basic-auth)  [ $# -ge 2 ] || die "--basic-auth needs a value"; if [ "$2" = - ]; then READ_BASIC=1; else BASIC=$2; fi; shift 2 ;;
    --pass)        [ "${2:-}" = - ] || die "--pass only accepts '-' (password is read from stdin)"; AUTH_MODE=pass; READ_PASS=1; shift 2 ;;
    --ssh-key)     [ $# -ge 2 ] || die "--ssh-key needs a value"; AUTH_MODE=key; SSH_KEY=$2; shift 2 ;;
    --op-ref)      [ $# -ge 2 ] || die "--op-ref needs a value"; AUTH_MODE=op; OP_REF=$2; shift 2 ;;
    --cf-access-id)     [ $# -ge 2 ] || die "--cf-access-id needs a value"; CF_ID=$2; shift 2 ;;
    --cf-access-secret) [ "${2:-}" = - ] || die "--cf-access-secret only accepts '-' (read from stdin)"; READ_CFSEC=1; shift 2 ;;
    -h|--help)     sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 0 ;;
    *)             die "unknown arg: $1" ;;
  esac
done

[ -n "$HOST" ] && [ -n "$SUSER" ] && [ -n "$REMOTE" ] && [ -n "$URL" ] \
  || die "required: --host --user --remote-dir --url"
[ -n "$AUTH_MODE" ] || die "pick one auth mode: --pass - | --ssh-key PATH | --op-ref op://..."
case "$TOOL" in ''|openclaw|codex) ;; *) die "--tool must be openclaw or codex (got '$TOOL')";; esac
# Cloudflare Access service token (optional) — needs BOTH parts or neither.
if [ -n "$CF_ID" ] || [ "$READ_CFSEC" = 1 ]; then
  { [ -n "$CF_ID" ] && [ "$READ_CFSEC" = 1 ]; } || die "Cloudflare Access needs BOTH --cf-access-id and --cf-access-secret -"
fi

# Config is BOTH sourced by bash (publish.sh) AND split on first '=' (sftp_helper.py), so every
# value must be raw and shell-safe. Reject values that would break `. config` — no quoting can
# satisfy both readers. Keys/urls are unlikely to contain these; a password might.
# Allowlist (robust): only chars that are safe both as an unquoted `KEY=value` bash source
# AND as a raw split value in sftp_helper.py. Anything else is rejected. '-' is last = literal.
_shell_safe() { case "$1" in *[!A-Za-z0-9_.:/@%+-]*) return 1;; *) return 0;; esac; }
for v in "$HOST" "$SUSER" "$PORT" "$REMOTE" "$URL" "$TOOL" "$BASIC" "$SSH_KEY" "$OP_REF" "$CF_ID"; do
  [ -z "$v" ] || _shell_safe "$v" || die "value contains characters that break config sourcing: '$v'"
done

# Secrets come from stdin, never argv (argv leaks via ps/history). Fixed line order for the
# ones requested with -: SFTP password, basic-auth, cf-access-secret. Validated before any
# side effect so a bad secret fails fast.
PASS=''
if [ "$READ_PASS" = 1 ]; then
  IFS= read -r PASS || true
  [ -n "$PASS" ] || die "--pass - was given but stdin was empty"
  _shell_safe "$PASS" || die "password contains characters this config format cannot store (space, quote, \$, backtick, backslash, or leading #) — use --ssh-key instead"
fi
if [ "$READ_BASIC" = 1 ]; then
  IFS= read -r BASIC || true
  [ -n "$BASIC" ] || die "--basic-auth - was given but stdin had no (further) line"
  _shell_safe "$BASIC" || die "basic-auth value has characters this config format cannot store — check user:pass"
fi
if [ "$READ_CFSEC" = 1 ]; then
  IFS= read -r CF_SECRET || true
  [ -n "$CF_SECRET" ] || die "--cf-access-secret - was given but stdin had no (further) line"
  _shell_safe "$CF_SECRET" || die "cf-access-secret has characters this config format cannot store"
fi

mkdir -p "$CFG_DIR"

# Pin the host key — fail closed. An artifact must never upload to an unverified host.
tmpkh=$(mktemp)
if ! ssh-keyscan -p "$PORT" "$HOST" > "$tmpkh" 2>/dev/null || [ ! -s "$tmpkh" ]; then
  rm -f "$tmpkh"; die "ssh-keyscan returned no key for $HOST:$PORT — check host/port/network"
fi
mv "$tmpkh" "$KNOWN"; chmod 600 "$KNOWN"
err "pinned host key -> $KNOWN"

# Refuse a symlinked config path — a planted symlink would redirect the plaintext secrets to
# an attacker-readable target, and a trailing chmod would "fix" the wrong file (TOCTOU on a
# shared config dir). Same defense the host-key pin gets by writing a fresh file.
[ -L "$CONFIG" ] && die "refusing: $CONFIG is a symlink (possible tamper) — remove it and rerun"

# Back up an existing (regular) config before overwriting it.
[ -f "$CONFIG" ] && cp "$CONFIG" "$CONFIG.bak-$(date -u +%Y%m%dT%H%M%SZ)" && err "backed up previous config"

# Atomic write: fill a fresh 0600 temp file in the same dir, then rename over $CONFIG — the
# secrets are never briefly world-readable and no symlink at $CONFIG can capture the plaintext.
tmpcfg=$(mktemp "$CFG_DIR/config.XXXXXX")
{
  printf 'SFTP_HOST=%s\n' "$HOST"
  printf 'SFTP_USER=%s\n' "$SUSER"
  printf 'SFTP_PORT=%s\n' "$PORT"
  printf 'REMOTE_DIR=%s\n' "$REMOTE"
  printf 'PUBLIC_BASE_URL=%s\n' "$URL"
  [ -n "$TOOL" ]  && printf 'DEFAULT_TOOL=%s\n' "$TOOL"
  [ -n "$BASIC" ] && printf 'BASIC_AUTH=%s\n' "$BASIC"
  [ -n "$CF_ID" ] && printf 'CF_ACCESS_CLIENT_ID=%s\n' "$CF_ID"
  [ -n "$CF_SECRET" ] && printf 'CF_ACCESS_CLIENT_SECRET=%s\n' "$CF_SECRET"
  case "$AUTH_MODE" in
    pass) printf 'SFTP_PASS=%s\n' "$PASS" ;;
    key)  printf 'SSH_KEY=%s\n'   "$SSH_KEY" ;;
    op)   printf 'OP_KEY_REF=%s\n' "$OP_REF" ;;
  esac
} > "$tmpcfg"
chmod 600 "$tmpcfg"
mv -f "$tmpcfg" "$CONFIG"
err "wrote config -> $CONFIG (mode 600)"

if [ "$AUTH_MODE" = pass ] && ! python3 -c 'import paramiko' 2>/dev/null; then
  err "WARNING: password auth needs python3-paramiko — install with: pip3 install paramiko"
fi
err "setup complete. Smoke test:"
err "  printf '<title>t</title><p>hi</p>' > /tmp/s.html && bash $(cd "$(dirname "$0")" && pwd)/publish.sh --slug smoke --tool ${TOOL:-codex} /tmp/s.html"
