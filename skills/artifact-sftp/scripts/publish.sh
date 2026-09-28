#!/usr/bin/env bash
# artifact-sftp — publish a self-contained HTML artifact to the owner's SFTP or S3/Cloudflare R2 host.
#
# Contract (stable — agents parse this):
#   - On success the LAST line of stdout is the artifact URL. Everything else -> stderr.
#   - stderr always carries a parseable `read-back: <path>` line naming the local copy of the
#     upload (the same stamped bytes the server serves). Private artifacts cannot be fetched
#     over HTTP, so read them back from that path (or from SFTP/S3, see SKILL.md).
#   - Exit codes: 0 ok | 2 usage | 3 config/auth | 4 secret scan blocked | 5 upload failed | 6 verify failed
#                 | 7 private artifact exposed | 8 private protection inconclusive | 9 local archive failed
#
# usage: publish.sh --slug SLUG [--tool NAME] [--public] [--force] [--dry-run] [--allow-sensitive] FILE.html
#        publish.sh --list   [--tool NAME]
#        publish.sh --delete SLUG [--tool NAME] [--public]
#
# Config lives ONLY in ~/.config/artifact-sftp/config (mode 0600). No env overrides —
# a fixed path keeps injected instructions from redirecting uploads to another host.
set -euo pipefail
umask 077

if [ "${ARTIFACT_SFTP_MCP_CALL:-}" != '1' ]; then
  printf '%s\n' 'ERROR: publish.sh is internal to Artifact SFTP MCP; AI agents must use artifact_sftp.publish.' >&2
  exit 10
fi

CONFIG="$HOME/.config/artifact-sftp"
CONFIG="$CONFIG/config"
MANIFEST="$HOME/.config/artifact-sftp/published.list"
SLUG_RE='^[a-z0-9][a-z0-9-]{0,62}$'
MAX_BYTES=$((5 * 1024 * 1024))

err() { printf '%s\n' "$*" >&2; }
die() { local code=$1; shift; err "ERROR: $*"; exit "$code"; }

# ---------- portable primitives (linux/GNU + mac/BSD + git-bash/WSL) ----------
_stat_perm() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
_stat_size() { stat -c '%s' "$1" 2>/dev/null || stat -f '%z' "$1"; }
_sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; }

_public_base_url_valid() {
  local url=$1 authority host port
  case "$url" in https://*) ;; *) return 1 ;; esac
  case "$url" in *'?'*|*'#'*) return 1 ;; esac
  case "$url" in */) return 1 ;; esac
  authority=${url#https://}
  case "$authority" in */*) return 1 ;; esac
  authority=${authority%%/*}
  case "$authority" in ''|:*|*@*|*:) return 1 ;; esac
  if [[ "$authority" == *:* ]]; then
    host=${authority%%:*}
    port=${authority#*:}
    [ -n "$host" ] || return 1
    case "$port" in ''|*[!0-9]*) return 1 ;; esac
  fi
  return 0
}

if command -v timeout >/dev/null 2>&1; then _timeout() { timeout "$@"; }
elif command -v gtimeout >/dev/null 2>&1; then _timeout() { gtimeout "$@"; }
elif command -v perl >/dev/null 2>&1; then _timeout() { local t=$1; shift; perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; }
else _timeout() { shift; "$@"; }
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
    --ping) MODE=ping; shift ;;
    --delete|--unpublish) [ $# -ge 2 ] || usage; MODE=delete; SLUG=$2; shift 2 ;;
    -h|--help) usage ;;
    -*) err "unknown option: $1"; usage ;;
    *) FILE=$1; shift ;;
  esac
done

# ---------- config ----------
[ -f "$CONFIG" ] || die 3 "config not found: $CONFIG (see references/setup.md)"
perm=$(_stat_perm "$CONFIG")
case "$perm" in 600|400) ;; *) die 3 "config $CONFIG must be mode 0600 (is $perm)";; esac

unset STORAGE_DRIVER SFTP_HOST SFTP_USER REMOTE_DIR PUBLIC_BASE_URL SFTP_PORT KNOWN_HOSTS \
      DEFAULT_TOOL SSH_KEY OP_KEY_REF SFTP_PASS \
      S3_ENDPOINT S3_BUCKET S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY S3_REGION \
      CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET DEFAULT_LANG DEFAULT_TIMEZONE

_load_config() {
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) die 3 "malformed line in $CONFIG (expected KEY=value)" ;; esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in
      STORAGE_DRIVER|SFTP_HOST|SFTP_USER|SFTP_PORT|REMOTE_DIR|PUBLIC_BASE_URL|DEFAULT_TOOL|KNOWN_HOSTS|\
      SFTP_PASS|SSH_KEY|OP_KEY_REF|\
      S3_ENDPOINT|S3_BUCKET|S3_ACCESS_KEY_ID|S3_SECRET_ACCESS_KEY|S3_REGION|\
      CF_ACCESS_CLIENT_ID|CF_ACCESS_CLIENT_SECRET|\
      DEFAULT_LANG|DEFAULT_TIMEZONE)
        printf -v "$key" '%s' "$value"
        ;;
      *) die 3 "unknown key in $CONFIG: $key" ;;
    esac
  done < "$CONFIG"
}
_load_config

STORAGE_DRIVER=${STORAGE_DRIVER:-sftp}
TOOL=${TOOL:-${DEFAULT_TOOL:-}}
case "$TOOL" in openclaw|codex|claude) ;; *) die 2 "--tool must be openclaw, codex or claude (got '${TOOL:-<empty>}')";; esac

if [ "$MODE" = publish ]; then
  : "${PUBLIC_BASE_URL:?missing in config}"
  _public_base_url_valid "$PUBLIC_BASE_URL" \
    || die 3 "PUBLIC_BASE_URL must be an HTTPS origin with a host, no path/query/fragment, and no trailing slash"
fi

_cfg_safe() { case "$1" in *[!A-Za-z0-9_.:/@%+-]*) return 1;; *) return 0;; esac; }
for _v in "${CF_ACCESS_CLIENT_ID:-}" "${CF_ACCESS_CLIENT_SECRET:-}"; do
  [ -z "$_v" ] || _cfg_safe "$_v" || die 3 "a verify-auth config value has characters unsafe for the curl -K config — fix CF_ACCESS_* in $CONFIG"
done
for _v in "${DEFAULT_LANG:-}" "${DEFAULT_TIMEZONE:-}"; do
  [ -z "$_v" ] || _cfg_safe "$_v" || die 3 "DEFAULT_LANG/DEFAULT_TIMEZONE has characters unsafe for HTML/shell interpolation"
done

CLEANUP_KEY=''
BATCH=''
STAMPED=''
PREINJECT=''
FONTED=''
DEFOOTED=''
LOCAL_INDEX_TMP=''
LOCAL_SNAPSHOT_TMP=''
LIVE_INDEX=''
cleanup() {
  if [ -n "$CLEANUP_KEY" ]; then rm -f "$CLEANUP_KEY"; fi
  if [ -n "$BATCH" ]; then rm -f "$BATCH"; fi
  if [ -n "$STAMPED" ]; then rm -f "$STAMPED"; fi
  if [ -n "$PREINJECT" ]; then rm -f "$PREINJECT"; fi
  if [ -n "$FONTED" ]; then rm -f "$FONTED"; fi
  if [ -n "$DEFOOTED" ]; then rm -f "$DEFOOTED"; fi
  if [ -n "$LOCAL_INDEX_TMP" ]; then rm -f "$LOCAL_INDEX_TMP"; fi
  if [ -n "$LIVE_INDEX" ]; then rm -f "$LIVE_INDEX"; fi
  if [ -n "$LOCAL_SNAPSHOT_TMP" ]; then rm -f "$LOCAL_SNAPSHOT_TMP"; fi
}
trap cleanup EXIT

# Initialize transport according to driver
if [ "$STORAGE_DRIVER" = "s3" ]; then
  : "${S3_ENDPOINT:?missing in config}" "${S3_BUCKET:?missing in config}"
  : "${S3_ACCESS_KEY_ID:?missing in config}" "${S3_SECRET_ACCESS_KEY:?missing in config}"
  S3_HELPER="$(cd "$(dirname "$0")" && pwd)/s3_helper.py"
  command -v python3 >/dev/null 2>&1 || die 3 "python3 is required for S3 driver"
else
  : "${SFTP_HOST:?missing in config}" "${SFTP_USER:?missing in config}"
  : "${REMOTE_DIR:?missing in config}"
  SFTP_PORT=${SFTP_PORT:-22}
  KNOWN_HOSTS=${KNOWN_HOSTS:-$HOME/.config/artifact-sftp/known_hosts}
  [ -f "$KNOWN_HOSTS" ] || die 3 "pinned known_hosts missing: $KNOWN_HOSTS (seed with ssh-keyscan — see references/setup.md)"

  SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10
            -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS"
            -P "$SFTP_PORT")

  HELPER="$(cd "$(dirname "$0")" && pwd)/sftp_helper.py"
  USE_PY=0
  if [ -n "${SFTP_PASS:-}" ]; then
    python3 -c 'import paramiko' 2>/dev/null \
      || die 3 "SFTP_PASS is set but python3-paramiko is not installed"
    USE_PY=1
  fi

  if [ "$USE_PY" = 1 ]; then
    :
  elif [ -n "${SSH_KEY:-}" ]; then
    SSH_OPTS+=(-i "$SSH_KEY")
  elif [ -n "${OP_KEY_REF:-}" ]; then
    OP_BIN=$(command -v op || true)
    if [ -z "$OP_BIN" ]; then
      OP_BIN=$(command -v op.exe || true)
    fi
    if [ -z "$OP_BIN" ]; then
      for p in /mnt/c/Users/*/AppData/Local/Programs/"1Password CLI"/op.exe; do
        [ -x "$p" ] && OP_BIN=$p && break
      done
    fi
    [ -n "$OP_BIN" ] || die 3 "no SSH_KEY in config and no op/op.exe found"
    CLEANUP_KEY=$(mktemp)
    _timeout 30 "$OP_BIN" read "$OP_KEY_REF" 2>/dev/null | tr -d '\r' > "$CLEANUP_KEY" \
      || die 3 "op read failed (1Password app locked or item missing: $OP_KEY_REF)"
    [ -s "$CLEANUP_KEY" ] || die 3 "op returned an empty key"
    SSH_OPTS+=(-i "$CLEANUP_KEY")
  fi
  DEST="$SFTP_USER@$SFTP_HOST"

  run_sftp() {
    _timeout 90 sftp -q "${SSH_OPTS[@]}" -b "$1" "$DEST" >&2
  }
fi

remote_versions() {
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    _timeout 90 python3 "$S3_HELPER" versions "$TOOL/$VIS/$SLUG" 2>/dev/null || true
  elif [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" versions "$RPATH" 2>/dev/null || true
  else
    BATCH=$(mktemp)
    printf -- '-ls -1 %s\n' "$RPATH" > "$BATCH"
    _timeout 90 sftp -q "${SSH_OPTS[@]}" -b "$BATCH" "$DEST" 2>/dev/null || true
  fi
}

# ---------- list ----------
if [ "$MODE" = list ]; then
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    _timeout 90 python3 "$S3_HELPER" list "$TOOL"
  elif [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" list "$REMOTE_DIR/$TOOL"
  else
    BATCH=$(mktemp)
    printf -- '-ls -1 %s/%s/private\n-ls -1 %s/%s/public\n' \
      "$REMOTE_DIR" "$TOOL" "$REMOTE_DIR" "$TOOL" > "$BATCH"
    _timeout 90 sftp -q "${SSH_OPTS[@]}" -b "$BATCH" "$DEST"
  fi
  exit 0
fi

# ---------- ping (bounded, no-write connection preflight) ----------
# setup_status(verify_connection=True) probes through here. For S3 this is a
# single max-keys=1 request instead of a full inventory walk, so a large
# bucket cannot blow the preflight timeout or memory. SFTP keeps its
# established two-directory listing probe.
if [ "$MODE" = ping ]; then
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    _timeout 90 python3 "$S3_HELPER" test_connection >&2 || die 3 "s3 connection preflight failed"
  elif [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" list "$REMOTE_DIR/$TOOL" >&2 || die 3 "sftp connection preflight failed"
  else
    BATCH=$(mktemp)
    printf -- '-ls -1 %s/%s/private\n-ls -1 %s/%s/public\n' \
      "$REMOTE_DIR" "$TOOL" "$REMOTE_DIR" "$TOOL" > "$BATCH"
    run_sftp "$BATCH" || die 3 "sftp connection preflight failed"
    rm -f "$BATCH"; BATCH=''
  fi
  exit 0
fi

# ---------- shared slug validation ----------
[ -n "$SLUG" ] || { err "--slug is required"; usage; }
[[ "$SLUG" =~ $SLUG_RE ]] || die 2 "invalid slug '$SLUG' (must match $SLUG_RE)"
if [ "$STORAGE_DRIVER" = "s3" ]; then
  RPATH="$TOOL/$VIS/$SLUG"
else
  RPATH="$REMOTE_DIR/$TOOL/$VIS/$SLUG"
fi

# ---------- delete / unpublish ----------
if [ "$MODE" = delete ]; then
  if [ "$DRY" = 1 ]; then
    printf 'dry-run: would delete %s\n' "$TOOL/$VIS/$SLUG"
    exit 0
  fi
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    _timeout 90 python3 "$S3_HELPER" delete "$RPATH" >&2 || die 5 "s3 delete failed for $RPATH"
  elif [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" delete "$RPATH" >&2 || die 5 "delete failed for $RPATH"
  else
    CHECK_BATCH=$(mktemp)
    printf -- 'ls -d %s\n' "$RPATH" > "$CHECK_BATCH"
    if run_sftp "$CHECK_BATCH" 2>/dev/null; then
      BATCH=$(mktemp)
      printf -- '-rm %s/*\nrmdir "%s"\n' "$RPATH" "$RPATH" > "$BATCH"
      run_sftp "$BATCH" || die 5 "delete failed for $RPATH"
    fi
  fi
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

# Secret scan
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

LOCAL_DOCS_DIR="$PWD/docs"
LOCAL_ARTIFACT_ROOT="$LOCAL_DOCS_DIR/artifacts"
LOCAL_ARTIFACT_DIR="$LOCAL_ARTIFACT_ROOT/$TOOL/$VIS/$SLUG"
LOCAL_INDEX_PATH="$LOCAL_ARTIFACT_DIR/index.html"

validate_local_archive_path() {
  local path
  for path in \
    "$LOCAL_DOCS_DIR" \
    "$LOCAL_ARTIFACT_ROOT" \
    "$LOCAL_ARTIFACT_ROOT/$TOOL" \
    "$LOCAL_ARTIFACT_ROOT/$TOOL/$VIS" \
    "$LOCAL_ARTIFACT_DIR"; do
    [ -L "$path" ] && die 9 "local archive path must not be a symlink: $path"
    if [ -e "$path" ] && [ ! -d "$path" ]; then
      die 9 "local archive path is not a directory: $path"
    fi
  done
}

validate_local_archive_path

if [ "$DRY" -eq 1 ]; then
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    err "dry-run: would upload $FILE -> s3://$S3_BUCKET/$RPATH/index.html"
  else
    err "dry-run: would upload $FILE -> $DEST:$RPATH/index.html"
  fi
  err "dry-run: would also save local copy -> $LOCAL_INDEX_PATH"
  printf '%s\n' "$URL"
  exit 0
fi

# Overwrite guard: refuse to clobber a remote slug this machine has no custody of.
# Custody = published from this machine (manifest), or a local copy is byte-identical to the live
# index.html: this project's docs/artifacts archive (a cloned project, e.g. after moving to
# another machine) or the read-back cache written by the read tool (read before edit). The live
# bytes are downloaded to compare, so an empty/forged file or a stale copy never matches and a
# newer remote version is never overwritten silently. For a public artifact the live bytes are not
# secret, so a match proves the copy is current, not that it came from this user's read.
READ_CACHE_INDEX="$HOME/.cache/artifact-sftp/remote/$TOOL/$VIS/$SLUG/index.html"
S3_READ_CACHE_INDEX="$HOME/.cache/artifact-sftp/remote-s3/$TOOL/$VIS/$SLUG/index.html"
live_index_custody() { # 0: a local copy equals the live index.html, 1: none does, 2: download failed
  local copy dl
  LIVE_INDEX=$(mktemp)
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    _timeout 90 python3 "$S3_HELPER" get "$RPATH/index.html" "$LIVE_INDEX" 2>/dev/null || return 2
  elif [ "$USE_PY" = 1 ]; then
    _timeout 90 python3 "$HELPER" get "$RPATH/index.html" "$LIVE_INDEX" 2>/dev/null || return 2
  else
    if [ -n "$BATCH" ]; then rm -f "$BATCH"; fi
    BATCH=$(mktemp)
    printf 'get "%s/index.html" "%s"\n' "$RPATH" "$LIVE_INDEX" > "$BATCH"
    dl=0; run_sftp "$BATCH" 2>/dev/null || dl=$?
    rm -f "$BATCH"; BATCH=''
    [ "$dl" -eq 0 ] || return 2
  fi
  [ -s "$LIVE_INDEX" ] || return 2
  for copy in "$LOCAL_INDEX_PATH" "$READ_CACHE_INDEX" "$S3_READ_CACHE_INDEX"; do
    if [ -f "$copy" ] && [ ! -L "$copy" ] && cmp -s "$LIVE_INDEX" "$copy"; then return 0; fi
  done
  return 1
}
require_custody() {
  local rc=0
  live_index_custody || rc=$?
  case "$rc" in
    0) ;;
    2) die 5 "remote $TOOL/$VIS/$SLUG exists but its live index.html could not be downloaded to verify custody — retry, or use --force to overwrite" ;;
    *) die 5 "remote $TOOL/$VIS/$SLUG already exists and no local copy (project docs/artifacts or read-back cache) matches its live index.html — read it first, or use --force to overwrite" ;;
  esac
}
if [ "$FORCE" -ne 1 ] && ! grep -qxF "$TOOL/$VIS/$SLUG" "$MANIFEST" 2>/dev/null; then
  if [ "$STORAGE_DRIVER" = "s3" ]; then
    exists=0; _timeout 90 python3 "$S3_HELPER" exists "$RPATH/index.html" 2>/dev/null || exists=$?
    case "$exists" in
      0) require_custody ;;
      1) : ;; # the slug is genuinely absent — safe to create
      *) die 5 "could not verify whether remote $TOOL/$VIS/$SLUG exists (s3 exists exit $exists) — refusing to risk overwriting an artifact without custody" ;;
    esac
  elif [ "$USE_PY" = 1 ]; then
    exists=0; _timeout 90 python3 "$HELPER" exists "$RPATH" 2>/dev/null || exists=$?
    if [ "$exists" -eq 0 ]; then require_custody; fi
  else
    BATCH=$(mktemp)
    printf 'ls "%s/index.html"\n' "$RPATH" > "$BATCH"
    if run_sftp "$BATCH" 2>/dev/null; then
      require_custody
    fi
  fi
fi

# ---------- version + timestamp stamp ----------
last=$(remote_versions | sed -nE "s|.*${SLUG}--([0-9]+)--[0-9TZ]+\.html$|\1|p" | sort -n | tail -1)
[ -n "$last" ] || last=0
VER=$((last + 1))
TS=$(date -u +%Y%m%dT%H%M%SZ)
VFILE="${SLUG}--${VER}--${TS}.html"
SNAPSHOT_URL="${URL}${VFILE}"

LANG_ATTR=${DEFAULT_LANG:-th}
TZ_NAME=${DEFAULT_TIMEZONE:-Asia/Bangkok}

PREINJECT=$(mktemp)
grep -qiE '<meta[^>]*charset' "$FILE" && HAS_CHARSET=1 || HAS_CHARSET=0
grep -qi '</head>'            "$FILE" && HAS_CLOSE_HEAD=1 || HAS_CLOSE_HEAD=0
grep -qi '<head'              "$FILE" && HAS_OPEN_HEAD=1 || HAS_OPEN_HEAD=0
grep -qiE '<html[^>]*lang='   "$FILE" && HAS_LANG=1 || HAS_LANG=0
grep -qi '<!doctype'          "$FILE" && HAS_DOCTYPE=1 || HAS_DOCTYPE=0
awk -v lang="$LANG_ATTR" \
    -v has_charset="$HAS_CHARSET" -v has_close_head="$HAS_CLOSE_HEAD" \
    -v has_open_head="$HAS_OPEN_HEAD" -v has_lang="$HAS_LANG" \
    -v has_doctype="$HAS_DOCTYPE" '
function add_html_lang(line,    lower, start) {
  lower = tolower(line)
  start = index(lower, "<html")
  return substr(line, 1, start + 4) " lang=\"" lang "\"" substr(line, start + 5)
}
function add_after_open_head(line, markup,    lower, start, end_at) {
  lower = tolower(line)
  start = index(lower, "<head")
  end_at = index(substr(line, start), ">")
  if (start == 0 || end_at == 0) return line
  end_at = start + end_at - 1
  return substr(line, 1, end_at) markup substr(line, end_at + 1)
}
function add_before_close_head(line, markup,    lower, start) {
  lower = tolower(line)
  start = index(lower, "</head")
  if (start == 0) return line
  return substr(line, 1, start - 1) markup substr(line, start)
}
BEGIN { cdone = has_charset; ldone = has_lang; nohead = !has_close_head && !has_open_head }
{
  lower = tolower($0)
  if (!ldone && index(lower, "<html")) { $0 = add_html_lang($0); ldone = 1; lower = tolower($0) }
  if (!cdone) {
    if (has_close_head && index(lower, "</head"))   { $0 = add_before_close_head($0, "<meta charset=\"utf-8\">\n"); cdone = 1 }
    else if (has_open_head && index(lower, "<head")) { $0 = add_after_open_head($0, "<meta charset=\"utf-8\">"); cdone = 1 }
    else if (nohead) {
      if (has_doctype && lower ~ /<!doctype/) { print "<head><meta charset=\"utf-8\"></head>"; cdone = 1 }
      else if (!has_doctype)                  { print "<head><meta charset=\"utf-8\"></head>"; cdone = 1 }
    }
  }
  print
}' "$FILE" > "$PREINJECT"

SARABUN_MARKUP='<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700&display=swap"><style data-artifact-sftp-font="sarabun">html,body,button,input,select,textarea{font-family:"Sarabun","Noto Sans Thai",system-ui,sans-serif}</style>'
if ! grep -Fqi 'data-artifact-sftp-font="sarabun"' "$PREINJECT"; then
  FONTED=$(mktemp)
  FIRST_HEAD_LINE=$(awk 'index(tolower($0), "<head") { print NR; exit }' "$PREINJECT")
  if [ -z "$FIRST_HEAD_LINE" ]; then
    LAST_HEAD_LINE=$(awk 'index(tolower($0), "</head>") { last = NR } END { if (last) print last }' "$PREINJECT")
  else
    LAST_HEAD_LINE=''
  fi
  if [ -n "$LAST_HEAD_LINE" ]; then
    awk -v target="$LAST_HEAD_LINE" -v font="$SARABUN_MARKUP" '
function stamp_last_head(line,    lower, start, pos, last) {
  lower = tolower(line)
  start = 1
  while ((pos = index(substr(lower, start), "</head>")) != 0) {
    last = start + pos - 1
    start = last + 7
  }
  return substr(line, 1, last - 1) font substr(line, last)
}
NR == target { print stamp_last_head($0); next }
{ print }
' "$PREINJECT" > "$FONTED"
  else
    [ -n "$FIRST_HEAD_LINE" ] || die 9 "could not add the Sarabun font declaration to artifact HTML"
    awk -v target="$FIRST_HEAD_LINE" -v font="$SARABUN_MARKUP" '
function stamp_open_head(line,    lower, start, close_at) {
  lower = tolower(line)
  start = index(lower, "<head")
  if (start == 0) return line
  close_at = index(substr(lower, start), ">")
  if (close_at == 0) return line
  close_at = start + close_at - 1
  return substr(line, 1, close_at) font substr(line, close_at + 1)
}
NR == target { print stamp_open_head($0); next }
{ print }
' "$PREINJECT" > "$FONTED"
  fi
else
  FONTED="$PREINJECT"
  PREINJECT=''
fi

# A republished artifact often starts from a previous read-back copy, which already
# carries the footer this publisher stamped last time. Appending a second one leaves
# the served page claiming two different versions at the bottom, with the stale one
# first. Drop any footer we previously stamped before adding the current one. Only
# same-line footers are removed: everything this script emits is single-line by
# construction, and a multi-line match would risk eating author markup.
DEFOOTED=$(mktemp)
awk '
{
  line = $0
  out = ""
  while (1) {
    start = index(tolower(line), "<footer data-artifact-meta")
    if (start == 0) break
    rest = substr(line, start)
    close_at = index(tolower(rest), "</footer>")
    if (close_at == 0) break
    out = out substr(line, 1, start - 1)
    line = substr(rest, close_at + 9)
  }
  print out line
}
' "$FONTED" > "$DEFOOTED"
mv "$DEFOOTED" "$FONTED"
DEFOOTED=''

TS_HUMAN=$(TZ="$TZ_NAME" date '+%Y-%m-%d %H:%M %Z' 2>/dev/null) || TS_HUMAN=$(date -u '+%Y-%m-%d %H:%M UTC')

PLUGIN_ROOT_DIR="${ARTIFACT_SFTP_PLUGIN_ROOT:-}"
if [ -z "$PLUGIN_ROOT_DIR" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
  PLUGIN_ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." 2>/dev/null && pwd)"
fi

PLUGIN_VER=''
if [ -n "$PLUGIN_ROOT_DIR" ] && [ -f "$PLUGIN_ROOT_DIR/plugin.json" ]; then
  PLUGIN_VER=$(awk -F'"' '/"version"[[:space:]]*:/ {print $4; exit}' "$PLUGIN_ROOT_DIR/plugin.json" 2>/dev/null || true)
fi

PLUGIN_LABEL=''
if [ -n "$PLUGIN_VER" ]; then
  PLUGIN_LABEL=" · artifact-sftp v${PLUGIN_VER}"
fi

FOOT="<footer data-artifact-meta style=\"max-width:860px;margin:2.5rem auto 0;padding-top:.8rem;border-top:1px solid #88888855;font:14px/1.6 system-ui;color:#666\">artifact: ${SLUG} · v${VER}${PLUGIN_LABEL} · created ${TS_HUMAN}</footer>"

STAMPED=$(mktemp)
LAST_BODY_LINE=$(awk 'index(tolower($0), "</body>") { last = NR } END { if (last) print last }' "$FONTED")
if [ -n "$LAST_BODY_LINE" ]; then
  awk -v target="$LAST_BODY_LINE" -v foot="$FOOT" '
function stamp_last(line,    lower, start, pos, last) {
  lower = tolower(line)
  start = 1
  while ((pos = index(substr(lower, start), "</body>")) != 0) {
    last = start + pos - 1
    start = last + 7
  }
  return substr(line, 1, last - 1) foot substr(line, last)
}
NR == target { print stamp_last($0); next }
{ print }
' "$FONTED" > "$STAMPED"
else
  cat "$FONTED" > "$STAMPED"
  printf '%s\n' "$FOOT" >> "$STAMPED"
fi


# Windows hosts: emit Windows drive paths so the Python host's pathlib accepts
# them (Git Bash prints /e/... which Windows resolves as a relative path).
wpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

LOCAL_SNAPSHOT_PATH="$LOCAL_ARTIFACT_DIR/$VFILE"

validate_local_archive_path
mkdir -p "$LOCAL_ARTIFACT_DIR" \
  || die 9 "could not create local archive directory: $LOCAL_ARTIFACT_DIR"
validate_local_archive_path

LOCAL_INDEX_TMP=$(mktemp "$LOCAL_ARTIFACT_DIR/.index.html.XXXXXX") \
  || die 9 "could not stage local index copy: $LOCAL_INDEX_PATH"
LOCAL_SNAPSHOT_TMP=$(mktemp "$LOCAL_ARTIFACT_DIR/.$VFILE.XXXXXX") \
  || die 9 "could not stage local snapshot copy: $LOCAL_SNAPSHOT_PATH"
cp "$STAMPED" "$LOCAL_INDEX_TMP" \
  || die 9 "could not write local index copy: $LOCAL_INDEX_PATH"
cp "$STAMPED" "$LOCAL_SNAPSHOT_TMP" \
  || die 9 "could not write local snapshot copy: $LOCAL_SNAPSHOT_PATH"
mv -f "$LOCAL_INDEX_TMP" "$LOCAL_INDEX_PATH" \
  || die 9 "could not install local index copy: $LOCAL_INDEX_PATH"
LOCAL_INDEX_TMP=''
mv -f "$LOCAL_SNAPSHOT_TMP" "$LOCAL_SNAPSHOT_PATH" \
  || die 9 "could not install local snapshot copy: $LOCAL_SNAPSHOT_PATH"
LOCAL_SNAPSHOT_TMP=''
err "read-back: $(wpath "$LOCAL_INDEX_PATH")"
err "snapshot: $(wpath "$LOCAL_SNAPSHOT_PATH")"

# ---------- upload ----------
if [ "$STORAGE_DRIVER" = "s3" ]; then
  _timeout 120 python3 "$S3_HELPER" upload "$STAMPED" "$RPATH" "$VFILE" "$VIS" >&2 || die 5 "s3 upload failed for $RPATH"
elif [ "$USE_PY" = 1 ]; then
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
    printf -- '-chmod 644 "%s/index.html"\n' "$RPATH"
    printf 'put "%s" "%s/%s"\n' "$STAMPED" "$RPATH" "$VFILE"
    printf -- '-chmod 644 "%s/%s"\n' "$RPATH" "$VFILE"
  } > "$BATCH"
  run_sftp "$BATCH" || die 5 "sftp upload failed for $RPATH"
fi
err "published v${VER} (snapshot: ${VFILE})"

mkdir -p "$(dirname "$MANIFEST")"
grep -qxF "$TOOL/$VIS/$SLUG" "$MANIFEST" 2>/dev/null || printf '%s/%s/%s\n' "$TOOL" "$VIS" "$SLUG" >> "$MANIFEST"

# ---------- verify ----------
verify_url() {
  local cfg=$1 target=$2 body hdr code want got
  body=$(mktemp); hdr=$(mktemp)
  code=$(printf '%s' "$cfg" | _timeout 30 curl -q -sS -K - -o "$body" -D "$hdr" -w '%{http_code}' "${target}?cb=$$") \
    || { rm -f "$body" "$hdr"; return 1; }
  if [ "$code" != 200 ]; then
    if [ "$code" = 302 ] && grep -qiE '^location:.*(cloudflareaccess\.com|/cdn-cgi/access/)' "$hdr"; then
      rm -f "$body" "$hdr"; return 2
    fi
    if [ "$code" = 401 ] || [ "$code" = 403 ]; then
      rm -f "$body" "$hdr"; return 3
    fi
    rm -f "$body" "$hdr"; return 1
  fi
  want=$(_sha256 < "$STAMPED" | cut -d' ' -f1)
  got=$(_sha256 < "$body" | cut -d' ' -f1)
  rm -f "$body" "$hdr"
  [ "$got" = "$want" ]
}

verify_pair() {
  local cfg=$1 rc=0
  verify_url "$cfg" "$URL" || rc=$?
  [ "$rc" -eq 0 ] || return "$rc"
  verify_url "$cfg" "$SNAPSHOT_URL" || rc=$?
  return "$rc"
}

probe_private() {
  local target=$1 label=$2 rc=0
  verify_url '' "$target" || rc=$?
  case "$rc" in
    0)
      err "EXPOSED: private $label is readable by unauthenticated requests. It is NOT private."
      err "The content is live and readable by anyone with the URL. Take it down now:"
      err "  $0 --delete $SLUG --tool $TOOL"
      err "Then make the host require auth on /$TOOL/private/ before republishing."
      return 7
      ;;
    2|3)
      return 0
      ;;
    *)
      err "ERROR: could not prove that private $label is protected (anonymous probe inconclusive); URL withheld."
      return 8
      ;;
  esac
}

VERIFY_CFG=''
if [ -n "${CF_ACCESS_CLIENT_ID:-}" ] && [ -n "${CF_ACCESS_CLIENT_SECRET:-}" ]; then
  VERIFY_CFG="header = \"CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}\"
header = \"CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}\"
"
fi

rc=0
if [ "$VIS" = public ]; then
  verify_pair '' || rc=$?
  case $rc in
    0) err "verified: served content matches local sha256" ;;
    2) err "note: uploaded; public path unexpectedly behind Cloudflare Access — HTTP verify skipped" ;;
    *) die 6 "uploaded but $URL does not serve the expected content" ;;
  esac
elif [ -n "$VERIFY_CFG" ]; then
  verify_pair "$VERIFY_CFG" || rc=$?
  case $rc in
    0) err "verified: served content matches local sha256 (authenticated)" ;;
    2) err "note: private artifact uploaded; it is gated by Cloudflare Access and these credentials do not satisfy it — HTTP verify skipped. Set CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET in the config to enable verification." ;;
    *) die 6 "uploaded but $URL does not serve the expected content (authenticated)" ;;
  esac
else
  err "note: private artifact uploaded; HTTP verify skipped (no Cloudflare Zero Trust service token in config)"
fi

if [ "$VIS" != public ]; then
  private_rc=0
  probe_private "$URL" "index.html" || private_rc=$?
  [ "$private_rc" -eq 0 ] || exit "$private_rc"
  probe_private "$SNAPSHOT_URL" "the versioned snapshot" || private_rc=$?
  [ "$private_rc" -eq 0 ] || exit "$private_rc"
fi

if [ "$VIS" = public ]; then
  err "WARNING: PUBLIC artifact — anyone with the URL can read it"
else
  err "verified private: an unauthenticated request does not return the content"
fi
printf '%s\n' "$URL"
