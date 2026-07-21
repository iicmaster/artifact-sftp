#!/usr/bin/env bash
# artifact-sftp — publish a self-contained HTML artifact to the owner's SFTP web host.
#
# Contract (stable — agents parse this):
#   - On success the LAST line of stdout is the artifact URL. Everything else -> stderr.
#   - Exit codes: 0 ok | 2 usage | 3 config/auth | 4 secret scan blocked | 5 upload failed | 6 verify failed
#
# usage: publish.sh --slug SLUG [--tool NAME] [--public] [--force] [--dry-run] [--allow-sensitive] FILE.html
#        publish.sh --list   [--tool NAME]
#        publish.sh --delete SLUG [--tool NAME] [--public]
#
# Config lives ONLY in ~/.config/artifact-sftp/config (mode 0600). No env overrides —
# a fixed path keeps injected instructions from redirecting uploads to another host.
set -euo pipefail
umask 077

CONFIG="$HOME/.config/artifact-sftp/config"
MANIFEST="$HOME/.config/artifact-sftp/published.list"
SLUG_RE='^[a-z0-9][a-z0-9-]{0,62}$'
MAX_BYTES=$((5 * 1024 * 1024))

err() { printf '%s\n' "$*" >&2; }
die() { local code=$1; shift; err "ERROR: $*"; exit "$code"; }

# ---------- portable primitives (linux/GNU + mac/BSD + git-bash/WSL) ----------
# GNU and BSD stat take different flags; try GNU (-c) first, fall back to BSD (-f).
_stat_perm() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
_stat_size() { stat -c '%s' "$1" 2>/dev/null || stat -f '%z' "$1"; }
# sha256sum (coreutils) vs shasum -a 256 (mac); both print "<hash>  -", so cut f1 works.
_sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; }
# _timeout SECS cmd... — coreutils timeout / gtimeout / perl alarm (survives exec).
if command -v timeout >/dev/null 2>&1; then _timeout() { timeout "$@"; }
elif command -v gtimeout >/dev/null 2>&1; then _timeout() { gtimeout "$@"; }
elif command -v perl >/dev/null 2>&1; then _timeout() { local t=$1; shift; perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; }
else _timeout() { shift; "$@"; }  # ponytail: last resort — no timeout/gtimeout/perl (rare; mac/linux/git-bash all ship perl). Runs UNCAPPED: -o ConnectTimeout caps connect only, not a stalled mid-transfer, so a hung host could block. Install coreutils or perl to restore the cap.
fi

usage() {
  sed -n '8,10p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

# ---------- arg parse ----------
MODE=publish SLUG='' TOOL='' VIS=private FORCE=0 DRY=0 ALLOW_SENSITIVE=0 FILE=''
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) [ $# -ge 2 ] || usage; SLUG=$2; shift 2 ;;
    --tool) [ $# -ge 2 ] || usage; TOOL=$2; shift 2 ;;
    --public) VIS=public; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --allow-sensitive) ALLOW_SENSITIVE=1; shift ;;
    --list) MODE=list; shift ;;
    --delete) [ $# -ge 2 ] || usage; MODE=delete; SLUG=$2; shift 2 ;;
    -h|--help) usage ;;
    -*) err "unknown option: $1"; usage ;;
    *) FILE=$1; shift ;;
  esac
done

# ---------- config ----------
[ -f "$CONFIG" ] || die 3 "config not found: $CONFIG (see references/setup.md)"
perm=$(_stat_perm "$CONFIG")
case "$perm" in 600|400) ;; *) die 3 "config $CONFIG must be mode 0600 (is $perm)";; esac
# Config values must come from the file alone — a pre-exported KNOWN_HOSTS or SSH_KEY
# would defeat host-key pinning / key selection via the ${VAR:-default} fallbacks below.
unset SFTP_HOST SFTP_USER REMOTE_DIR PUBLIC_BASE_URL SFTP_PORT KNOWN_HOSTS \
      DEFAULT_TOOL SSH_KEY BASIC_AUTH OP_KEY_REF SFTP_PASS \
      CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET
# shellcheck disable=SC1090
. "$CONFIG"
: "${SFTP_HOST:?missing in config}" "${SFTP_USER:?missing in config}"
: "${REMOTE_DIR:?missing in config}" "${PUBLIC_BASE_URL:?missing in config}"
SFTP_PORT=${SFTP_PORT:-22}
KNOWN_HOSTS=${KNOWN_HOSTS:-$HOME/.config/artifact-sftp/known_hosts}
TOOL=${TOOL:-${DEFAULT_TOOL:-}}
case "$TOOL" in openclaw|codex) ;; *) die 2 "--tool must be openclaw or codex (got '${TOOL:-<empty>}')";; esac
[ -f "$KNOWN_HOSTS" ] || die 3 "pinned known_hosts missing: $KNOWN_HOSTS (seed with ssh-keyscan — see references/setup.md)"

# Defense in depth: setup.sh's allowlist only guards values it WRITES, but this config is
# sourced directly (`.`), so it may be hand-edited, restored from a backup, or appended to by
# another tool. Re-validate every value interpolated into the curl -K verify config here: a
# value with an embedded quote+newline (legal via bash $'...' quoting) would otherwise inject a
# rogue directive (e.g. url=) into -K and exfiltrate the credentials on the next private publish.
_cfg_safe() { case "$1" in *[!A-Za-z0-9_.:/@%+-]*) return 1;; *) return 0;; esac; }
for _v in "${BASIC_AUTH:-}" "${CF_ACCESS_CLIENT_ID:-}" "${CF_ACCESS_CLIENT_SECRET:-}"; do
  [ -z "$_v" ] || _cfg_safe "$_v" || die 3 "a verify-auth config value has characters unsafe for the curl -K config (allowed: A-Za-z0-9 _.:/@%+-) — fix BASIC_AUTH/CF_ACCESS_* in $CONFIG"
done

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10
          -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS"
          -P "$SFTP_PORT")

# Transport: OpenSSH sftp with key auth, OR the paramiko helper when the account is
# password-only (SFTP_PASS in config). Never interactive — no prompt can hang an agent.
HELPER="$(cd "$(dirname "$0")" && pwd)/sftp_helper.py"
USE_PY=0
if [ -n "${SFTP_PASS:-}" ]; then
  python3 -c 'import paramiko' 2>/dev/null \
    || die 3 "SFTP_PASS is set but python3-paramiko is not installed"
  USE_PY=1
fi

CLEANUP_KEY=''
BATCH=''
STAMPED=''
cleanup() {
  # if-statements, not &&-lists: a false condition in an EXIT trap under set -e
  # would otherwise override the script's real exit code with 1.
  if [ -n "$CLEANUP_KEY" ]; then rm -f "$CLEANUP_KEY"; fi
  if [ -n "$BATCH" ]; then rm -f "$BATCH"; fi
  if [ -n "$STAMPED" ]; then rm -f "$STAMPED"; fi
}
trap cleanup EXIT
if [ "$USE_PY" = 1 ]; then
  : # paramiko helper reads config itself; SSH_OPTS unused
elif [ -n "${SSH_KEY:-}" ]; then
  SSH_OPTS+=(-i "$SSH_KEY")
elif [ -n "${OP_KEY_REF:-}" ]; then
  # 1Password fallback: op (native) or op.exe (WSL interop; needs desktop app unlocked).
  OP_BIN=$(command -v op || true)
  if [ -z "$OP_BIN" ]; then
    for p in /mnt/c/Users/*/AppData/Local/Programs/"1Password CLI"/op.exe; do
      [ -x "$p" ] && OP_BIN=$p && break
    done
  fi
  [ -n "$OP_BIN" ] || die 3 "no SSH_KEY in config and no op/op.exe found"
  CLEANUP_KEY=$(mktemp)
  # tr -d '\r': op.exe emits CRLF, which silently breaks key parsing.
  _timeout 30 "$OP_BIN" read "$OP_KEY_REF" 2>/dev/null | tr -d '\r' > "$CLEANUP_KEY" \
    || die 3 "op read failed (1Password app locked or item missing: $OP_KEY_REF)"
  [ -s "$CLEANUP_KEY" ] || die 3 "op returned an empty key"
  SSH_OPTS+=(-i "$CLEANUP_KEY")
fi
DEST="$SFTP_USER@$SFTP_HOST"

run_sftp() { # run_sftp <batch-file>
  _timeout 90 sftp -q "${SSH_OPTS[@]}" -b "$1" "$DEST" >&2
}

remote_versions() { # prints existing entries of $RPATH on stdout (empty if dir missing)
  if [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" versions "$RPATH" 2>/dev/null || true
  else
    BATCH=$(mktemp)
    printf -- '-ls -1 %s\n' "$RPATH" > "$BATCH"
    _timeout 90 sftp -q "${SSH_OPTS[@]}" -b "$BATCH" "$DEST" 2>/dev/null || true
  fi
}

# ---------- list ----------
if [ "$MODE" = list ]; then
  if [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" list "$REMOTE_DIR/$TOOL"
  else
    BATCH=$(mktemp)
    printf -- '-ls -1 %s/%s/private\n-ls -1 %s/%s/public\n' \
      "$REMOTE_DIR" "$TOOL" "$REMOTE_DIR" "$TOOL" > "$BATCH"
    _timeout 90 sftp -q "${SSH_OPTS[@]}" -b "$BATCH" "$DEST"
  fi
  exit 0
fi

# ---------- shared slug validation ----------
[ -n "$SLUG" ] || { err "--slug is required"; usage; }
[[ "$SLUG" =~ $SLUG_RE ]] || die 2 "invalid slug '$SLUG' (must match $SLUG_RE)"
RPATH="$REMOTE_DIR/$TOOL/$VIS/$SLUG"

# ---------- delete ----------
if [ "$MODE" = delete ]; then
  if [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" delete "$RPATH" >&2 || die 5 "delete failed for $RPATH"
  else
    # rm with glob: remove index.html and all versioned snapshots
    BATCH=$(mktemp)
    printf -- '-rm %s/*\nrmdir "%s"\n' "$RPATH" "$RPATH" > "$BATCH"
    run_sftp "$BATCH" || die 5 "delete failed for $RPATH"
  fi
  # drop from manifest so a future publish of this slug re-checks remote existence
  if [ -f "$MANIFEST" ]; then
    grep -vxF "$TOOL/$VIS/$SLUG" "$MANIFEST" > "$MANIFEST.new" || true
    mv "$MANIFEST.new" "$MANIFEST"
  fi
  err "deleted: $TOOL/$VIS/$SLUG"
  exit 0
fi

# ---------- publish: input validation ----------
[ -n "$FILE" ] || { err "FILE.html is required"; usage; }
[ -L "$FILE" ] && die 2 "symlinks are rejected: $FILE"
[ -f "$FILE" ] || die 2 "not a regular file: $FILE"
case "$FILE" in *.html|*.htm) ;; *) die 2 "only .html accepted (agent converts md to HTML first)";; esac
case "$FILE" in *$'\n'*|*'"'*) die 2 "unsafe characters in filename";; esac
size=$(_stat_size "$FILE")
[ "$size" -le "$MAX_BYTES" ] || die 2 "file too large: $size bytes (max $MAX_BYTES)"

# Secret scan — enforcement, not advice. Publishing is exfiltration if this fires.
if [ "$ALLOW_SENSITIVE" -ne 1 ]; then
  if grep -qE -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' \
              -e 'AKIA[0-9A-Z]{16}' \
              -e 'ghp_[A-Za-z0-9]{20,}' \
              -e 'sk-(ant-)?[A-Za-z0-9_-]{20,}' \
              -e 'xox[baprs]-[A-Za-z0-9-]+' \
              -e 'op://' "$FILE"; then
    die 4 "possible secret detected in $FILE — refusing to publish (override: --allow-sensitive)"
  fi
fi

URL="$PUBLIC_BASE_URL/$TOOL/$VIS/$SLUG/"

if [ "$DRY" -eq 1 ]; then
  err "dry-run: would upload $FILE -> $DEST:$RPATH/index.html"
  printf '%s\n' "$URL"
  exit 0
fi

# Overwrite guard: a slug this machine never published needs --force to clobber.
if [ "$FORCE" -ne 1 ] && ! grep -qxF "$TOOL/$VIS/$SLUG" "$MANIFEST" 2>/dev/null; then
  if [ "$USE_PY" = 1 ]; then
    exists=0; _timeout 90 python3 "$HELPER" exists "$RPATH" 2>/dev/null || exists=$?
    [ "$exists" -eq 0 ] && die 5 "remote $TOOL/$VIS/$SLUG already exists and is not in the local manifest — use --force to overwrite"
  else
    BATCH=$(mktemp)
    printf 'ls "%s/index.html"\n' "$RPATH" > "$BATCH"
    if run_sftp "$BATCH" 2>/dev/null; then
      die 5 "remote $TOOL/$VIS/$SLUG already exists and is not in the local manifest — use --force to overwrite"
    fi
  fi
fi

# ---------- version + timestamp stamp ----------
# Naming rule: every publish also keeps a snapshot {slug}--{version}--{timestamp}.html
# next to index.html; version = max existing on the server + 1 (cross-machine safe).
last=$(remote_versions | sed -nE "s|.*${SLUG}--([0-9]+)--[0-9TZ]+\.html$|\1|p" | sort -n | tail -1)
[ -n "$last" ] || last=0
VER=$((last + 1))
TS=$(date -u +%Y%m%dT%H%M%SZ)
VFILE="${SLUG}--${VER}--${TS}.html"

# Stamp creation time + version into the page itself so every viewer can see it.
STAMPED=$(mktemp)
TS_HUMAN=$(date -u '+%Y-%m-%d %H:%M UTC')
FOOT="<footer data-artifact-meta style=\"max-width:860px;margin:2.5rem auto 0;padding-top:.8rem;border-top:1px solid #88888855;font:12px/1.5 system-ui;color:#888\">artifact: ${SLUG} · v${VER} · created ${TS_HUMAN}</footer>"
if grep -q '</body>' "$FILE"; then
  awk -v foot="$FOOT" '!done && index($0,"</body>") { sub(/<\/body>/, foot "</body>"); done=1 } { print }' "$FILE" > "$STAMPED"
else
  cat "$FILE" > "$STAMPED"
  printf '%s\n' "$FOOT" >> "$STAMPED"
fi

# ---------- upload (atomic: put tmp, then rename; plus versioned snapshot) ----------
if [ "$USE_PY" = 1 ]; then
  _timeout 120 python3 "$HELPER" upload "$STAMPED" "$RPATH" "$VFILE" >&2 || die 5 "sftp upload failed for $RPATH"
else
BATCH=$(mktemp)
{
  printf -- '-mkdir %s/%s\n'    "$REMOTE_DIR" "$TOOL"
  printf -- '-mkdir %s/%s/%s\n' "$REMOTE_DIR" "$TOOL" "$VIS"
  printf -- '-mkdir %s\n'       "$RPATH"
  printf 'put "%s" "%s/index.html.tmp"\n' "$STAMPED" "$RPATH"
  printf -- '-rm "%s/index.html"\n' "$RPATH"
  printf 'rename "%s/index.html.tmp" "%s/index.html"\n' "$RPATH" "$RPATH"
  # -chmod: some sftp-servers lack SITE CHMOD; by this point rename already succeeded,
  # so a chmod failure must not turn a live upload into exit 5.
  printf -- '-chmod 644 "%s/index.html"\n' "$RPATH"
  printf 'put "%s" "%s/%s"\n' "$STAMPED" "$RPATH" "$VFILE"
  printf -- '-chmod 644 "%s/%s"\n' "$RPATH" "$VFILE"
} > "$BATCH"
run_sftp "$BATCH" || die 5 "sftp upload failed for $RPATH"
fi
err "published v${VER} (snapshot: ${VFILE})"

mkdir -p "$(dirname "$MANIFEST")"
grep -qxF "$TOOL/$VIS/$SLUG" "$MANIFEST" 2>/dev/null || printf '%s/%s/%s\n' "$TOOL" "$VIS" "$SLUG" >> "$MANIFEST"

# ---------- verify (content hash, not just HTTP 200) ----------
# Returns 0 = served bytes match; 1 = real mismatch/error; 2 = gated by Cloudflare Access
# (a 302 to the Access login — these credentials can't see the artifact, so we cannot verify,
# but the upload itself is fine). No -f: we inspect the status code ourselves so a 302 gate is
# distinguishable from a 4xx/5xx failure.
# Auth goes to curl via a -K config on STDIN, never argv — a header/user on the command line
# would expose BASIC_AUTH / the CF service secret to `ps` for the fetch's lifetime.
verify_url() {  # $1 = curl config text (may be empty); 0=match 1=fail 2=Cloudflare-Access-gated
  local body hdr code want got
  body=$(mktemp); hdr=$(mktemp)
  code=$(printf '%s' "$1" | _timeout 30 curl -sS -K - -o "$body" -D "$hdr" -w '%{http_code}' "${URL}index.html?cb=$$") \
    || { rm -f "$body" "$hdr"; return 1; }
  if [ "$code" != 200 ]; then
    if [ "$code" = 302 ] && grep -qiE '^location:.*(cloudflareaccess\.com|/cdn-cgi/access/)' "$hdr"; then
      rm -f "$body" "$hdr"; return 2
    fi
    rm -f "$body" "$hdr"; return 1
  fi
  want=$(_sha256 < "$STAMPED" | cut -d' ' -f1)
  got=$(_sha256 < "$body" | cut -d' ' -f1)
  rm -f "$body" "$hdr"
  [ "$got" = "$want" ]
}

# Build the curl auth config (kept off argv): CF Access service token and/or basic auth, from
# config only. Values are shell-safe per setup.sh's allowlist, so no quote can escape the config.
VERIFY_CFG=''
if [ -n "${CF_ACCESS_CLIENT_ID:-}" ] && [ -n "${CF_ACCESS_CLIENT_SECRET:-}" ]; then
  VERIFY_CFG="header = \"CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}\"
header = \"CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}\"
"
fi
[ -n "${BASIC_AUTH:-}" ] && VERIFY_CFG="${VERIFY_CFG}user = \"${BASIC_AUTH}\"
"

rc=0
if [ "$VIS" = public ]; then
  verify_url '' || rc=$?
  case $rc in
    0) err "verified: served content matches local sha256" ;;
    2) err "note: uploaded; public path unexpectedly behind Cloudflare Access — HTTP verify skipped" ;;
    *) die 6 "uploaded but $URL does not serve the expected content" ;;
  esac
elif [ -n "$VERIFY_CFG" ]; then
  verify_url "$VERIFY_CFG" || rc=$?
  case $rc in
    0) err "verified: served content matches local sha256 (authenticated)" ;;
    2) err "note: private artifact uploaded; it is gated by Cloudflare Access and these credentials do not satisfy it — HTTP verify skipped. Set CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET (a Zero Trust service token) in the config to enable verification." ;;
    *) die 6 "uploaded but $URL does not serve the expected content (authenticated)" ;;
  esac
else
  err "note: private artifact uploaded; HTTP verify skipped (no CF_ACCESS_* or BASIC_AUTH in config)"
fi

if [ "$VIS" = public ]; then
  err "WARNING: PUBLIC artifact — anyone with the URL can read it"
else
  err "private artifact — readable only with the configured credentials (basic auth or Cloudflare Access)"
fi
printf '%s\n' "$URL"
