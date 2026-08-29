#!/usr/bin/env bash
# Resolve an artifact-sftp URL or `read-back:` line to local archived bytes or remote SFTP fallback.
# Tier 1: Local archive resolution in the selected project's docs/artifacts/ tree (zero network I/O).
# Tier 2: Remote SFTP fetch fallback when reading cross-project, cross-machine, or private URLs.
set -euo pipefail
umask 077

if [ "${ARTIFACT_SFTP_MCP_CALL:-}" != '1' ]; then
  printf '%s\n' 'artifact-sftp-read: resolver is internal to Artifact SFTP MCP; AI agents must use artifact_sftp.read.' >&2
  exit 10
fi

CONFIG="$HOME/.config/artifact-sftp/config"
MAX_BYTES=$((5 * 1024 * 1024))

usage() {
  cat <<'EOF'
Usage: read-artifact.sh [--project DIR] [--cat] <artifact-url | read-back-path | archive-path>

Resolve an artifact-sftp reference to its local archive (Tier 1) or fetch it from remote SFTP (Tier 2).
With no option, print the absolute path on stdout. --cat streams the resolved artifact bytes instead.
EOF
}

fail() {
  local code=$1
  shift
  printf 'artifact-sftp-read: %s\n' "$*" >&2
  exit "$code"
}

_stat_perm() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
_stat_size() { stat -c '%s' "$1" 2>/dev/null || stat -f '%z' "$1"; }
if command -v timeout >/dev/null 2>&1; then _timeout() { timeout "$@"; }
elif command -v gtimeout >/dev/null 2>&1; then _timeout() { gtimeout "$@"; }
elif command -v perl >/dev/null 2>&1; then _timeout() { local t=$1; shift; perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; }
else _timeout() { shift; "$@"; }
fi

project=$PWD
mode=path

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project)
      [ "$#" -ge 2 ] || { usage >&2; fail 2 "--project needs a directory"; }
      project=$2
      shift 2
      ;;
    --cat)
      mode=cat
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      usage >&2
      fail 2 "unknown option: $1"
      ;;
    *)
      break
      ;;
  esac
done

[ "$#" -eq 1 ] || { usage >&2; fail 2 "provide exactly one artifact reference"; }
[ -d "$project" ] || fail 2 "project directory does not exist: $project"
project=$(cd -P "$project" && pwd)

reference=$1
case "$reference" in
  'read-back: '*) reference=${reference#read-back: } ;;
  'snapshot: '*) reference=${reference#snapshot: } ;;
esac
[ -n "$reference" ] || fail 2 "artifact reference is empty"

tool=''
vis=''
slug=''
target_file='index.html'
candidate=''

current_re='^/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/?$'
index_re='^/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/index\.html$'
snapshot_re='^/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/([a-z0-9][a-z0-9-]{0,62})--([1-9][0-9]*)--([0-9]{8}T[0-9]{6}Z)\.html$'

if [[ "$reference" == http://* ]]; then
  fail 2 "artifact URLs must use HTTPS: $reference"
elif [[ "$reference" == https://* ]]; then
  url_remainder=${reference#*://}
  url_path="/${url_remainder#*/}"
  url_path=${url_path%%\?*}
  url_path=${url_path%%\#*}

  if [[ "$url_path" =~ $current_re ]]; then
    tool=${BASH_REMATCH[1]}
    vis=${BASH_REMATCH[2]}
    slug=${BASH_REMATCH[3]}
    target_file="index.html"
  elif [[ "$url_path" =~ $index_re ]]; then
    tool=${BASH_REMATCH[1]}
    vis=${BASH_REMATCH[2]}
    slug=${BASH_REMATCH[3]}
    target_file="index.html"
  elif [[ "$url_path" =~ $snapshot_re ]]; then
    [ "${BASH_REMATCH[3]}" = "${BASH_REMATCH[4]}" ] \
      || fail 2 "snapshot filename does not match its artifact slug"
    tool=${BASH_REMATCH[1]}
    vis=${BASH_REMATCH[2]}
    slug=${BASH_REMATCH[3]}
    target_file="${BASH_REMATCH[4]}--${BASH_REMATCH[5]}--${BASH_REMATCH[6]}.html"
  else
    fail 2 "not an artifact-sftp URL: $reference"
  fi
  candidate="$project/docs/artifacts/$tool/$vis/$slug/$target_file"
elif [[ "$reference" = /* ]]; then
  abs_re='^.*/docs/artifacts/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/(index\.html|[a-z0-9][a-z0-9-]{0,62}--[1-9][0-9]*--[0-9]{8}T[0-9]{6}Z\.html)$'
  if [[ "$reference" =~ $abs_re ]]; then
    tool=${BASH_REMATCH[1]}
    vis=${BASH_REMATCH[2]}
    slug=${BASH_REMATCH[3]}
    target_file=${BASH_REMATCH[4]}
    if [ "$target_file" != "index.html" ] && [ "${target_file%%--*}" != "$slug" ]; then
      fail 2 "snapshot filename does not match its artifact slug"
    fi
    candidate=$reference
  else
    candidate=$reference
  fi
else
  rel_re='^(docs/artifacts/)?(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/(index\.html|[a-z0-9][a-z0-9-]{0,62}--[1-9][0-9]*--[0-9]{8}T[0-9]{6}Z\.html)$'
  if [[ "$reference" =~ $rel_re ]]; then
    tool=${BASH_REMATCH[2]}
    vis=${BASH_REMATCH[3]}
    slug=${BASH_REMATCH[4]}
    target_file=${BASH_REMATCH[5]}
    if [ "$target_file" != "index.html" ] && [ "${target_file%%--*}" != "$slug" ]; then
      fail 2 "snapshot filename does not match its artifact slug"
    fi
    candidate="$project/docs/artifacts/$tool/$vis/$slug/$target_file"
  else
    candidate="$project/$reference"
  fi
fi

# ==============================================================================
# Tier 1: Local-First Archive Check
# ==============================================================================
if [ -f "$candidate" ] && [ ! -L "$candidate" ]; then
  parent=$(cd -P "$(dirname "$candidate")" && pwd)
  resolved="$parent/$(basename "$candidate")"
  archive_root="$project/docs/artifacts/"
  case "$resolved" in
    "$archive_root"*)
      archive_rel=${resolved#"$archive_root"}
      archive_re='^(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/(index\.html|[a-z0-9][a-z0-9-]{0,62}--[1-9][0-9]*--[0-9]{8}T[0-9]{6}Z\.html)$'
      if [[ "$archive_rel" =~ $archive_re ]]; then
        if [ "${BASH_REMATCH[4]}" != 'index.html' ] && [ "${BASH_REMATCH[4]%%--*}" != "${BASH_REMATCH[3]}" ]; then
          fail 2 "snapshot filename does not match its artifact slug"
        fi
        if [ "$mode" = cat ]; then
          cat "$resolved"
        else
          printf '%s\n' "$resolved"
        fi
        exit 0
      fi
      ;;
    *)
      fail 2 "resolved path is outside this project's docs/artifacts: $resolved"
      ;;
  esac
elif [ -L "$candidate" ]; then
  fail 3 "refusing symlinked artifact archive: $candidate"
fi

# ==============================================================================
# Tier 2: Remote SFTP Fetch Fallback
# ==============================================================================
if [ -z "$tool" ] || [ -z "$vis" ] || [ -z "$slug" ] || [ -z "$target_file" ]; then
  fail 3 "local artifact archive is unavailable: $candidate (run from the publishing project or pass --project)"
fi

if [ ! -f "$CONFIG" ]; then
  fail 3 "local artifact archive is unavailable: $candidate (and remote SFTP config is not configured at $CONFIG)"
fi

perm=$(_stat_perm "$CONFIG")
case "$perm" in 600|400) ;; *) fail 3 "config $CONFIG must be mode 0600 (is $perm)";; esac

unset SFTP_HOST SFTP_USER REMOTE_DIR SFTP_PORT KNOWN_HOSTS SFTP_PASS SSH_KEY OP_KEY_REF PUBLIC_BASE_URL
_load_config() {
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) fail 3 "malformed line in $CONFIG (expected KEY=value)" ;; esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in
      SFTP_HOST|SFTP_USER|SFTP_PORT|REMOTE_DIR|KNOWN_HOSTS|SFTP_PASS|SSH_KEY|OP_KEY_REF|PUBLIC_BASE_URL)
        printf -v "$key" '%s' "$value"
        ;;
    esac
  done < "$CONFIG"
}
_load_config

: "${SFTP_HOST:?missing in config}" "${SFTP_USER:?missing in config}"
: "${REMOTE_DIR:?missing in config}"
SFTP_PORT=${SFTP_PORT:-22}
KNOWN_HOSTS=${KNOWN_HOSTS:-$HOME/.config/artifact-sftp/known_hosts}
[ -f "$KNOWN_HOSTS" ] || fail 3 "pinned known_hosts missing: $KNOWN_HOSTS (see references/setup.md)"

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
HELPER="$SCRIPT_DIR/../../artifact-sftp/scripts/sftp_helper.py"
if [ -n "${ARTIFACT_SFTP_PLUGIN_ROOT:-}" ] && [ -f "$ARTIFACT_SFTP_PLUGIN_ROOT/skills/artifact-sftp/scripts/sftp_helper.py" ]; then
  HELPER="$ARTIFACT_SFTP_PLUGIN_ROOT/skills/artifact-sftp/scripts/sftp_helper.py"
fi

USE_PY=0
if [ -n "${SFTP_PASS:-}" ]; then
  python3 -c 'import paramiko' 2>/dev/null \
    || fail 3 "SFTP_PASS is set but python3-paramiko is not installed"
  USE_PY=1
fi

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15
          -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS"
          -P "$SFTP_PORT")

CLEANUP_KEY=''
BATCH=''
TMP_DOWNLOAD=''
cleanup() {
  if [ -n "$CLEANUP_KEY" ]; then rm -f "$CLEANUP_KEY"; fi
  if [ -n "$BATCH" ]; then rm -f "$BATCH"; fi
  if [ -n "$TMP_DOWNLOAD" ]; then rm -f "$TMP_DOWNLOAD"; fi
}
trap cleanup EXIT

if [ "$USE_PY" = 1 ]; then
  : # paramiko helper
elif [ -n "${SSH_KEY:-}" ]; then
  SSH_OPTS+=(-i "$SSH_KEY")
elif [ -n "${OP_KEY_REF:-}" ]; then
  OP_BIN=$(command -v op || true)
  if [ -z "$OP_BIN" ]; then OP_BIN=$(command -v op.exe || true); fi
  [ -n "$OP_BIN" ] || fail 3 "no SSH_KEY in config and no op/op.exe found"
  CLEANUP_KEY=$(mktemp)
  _timeout 30 "$OP_BIN" read "$OP_KEY_REF" 2>/dev/null | tr -d '\r' > "$CLEANUP_KEY" \
    || fail 3 "op read failed ($OP_KEY_REF)"
  [ -s "$CLEANUP_KEY" ] || fail 3 "op returned an empty key"
  SSH_OPTS+=(-i "$CLEANUP_KEY")
fi

RPATH="$REMOTE_DIR/$tool/$vis/$slug/$target_file"
CACHE_DIR="$HOME/.cache/artifact-sftp/remote/$tool/$vis/$slug"
CACHE_FILE="$CACHE_DIR/$target_file"
mkdir -p "$CACHE_DIR"

TMP_DOWNLOAD=$(mktemp "$CACHE_DIR/dl.XXXXXX")
chmod 0600 "$TMP_DOWNLOAD"

dl_rc=0
if [ "$USE_PY" = 1 ]; then
  _timeout 30 python3 "$HELPER" get "$RPATH" "$TMP_DOWNLOAD" 2>/dev/null || dl_rc=$?
else
  BATCH=$(mktemp)
  printf -- 'get "%s" "%s"\n' "$RPATH" "$TMP_DOWNLOAD" > "$BATCH"
  _timeout 30 sftp -q "${SSH_OPTS[@]}" -b "$BATCH" "$SFTP_USER@$SFTP_HOST" 2>/dev/null || dl_rc=$?
  rm -f "$BATCH"
  BATCH=''
fi

if [ "$dl_rc" -ne 0 ] || [ ! -s "$TMP_DOWNLOAD" ]; then
  fail 3 "artifact not found locally in docs/artifacts nor on remote SFTP server: $tool/$vis/$slug/$target_file"
fi

dl_size=$(_stat_size "$TMP_DOWNLOAD")
if [ "$dl_size" -gt "$MAX_BYTES" ]; then
  rm -f "$TMP_DOWNLOAD"
  fail 3 "downloaded remote artifact exceeds 5 MiB safety limit ($dl_size bytes)"
fi

mv "$TMP_DOWNLOAD" "$CACHE_FILE"
TMP_DOWNLOAD=''
chmod 0600 "$CACHE_FILE"

if [ "$mode" = cat ]; then
  cat "$CACHE_FILE"
else
  printf '%s\n' "$CACHE_FILE"
fi
