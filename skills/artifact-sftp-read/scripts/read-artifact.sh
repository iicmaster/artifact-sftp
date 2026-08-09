#!/usr/bin/env bash
# Resolve an artifact-sftp URL or `read-back:` line to the local archived bytes.
# This deliberately performs no network I/O: private artifact URLs are viewer links behind
# Cloudflare Access, while the local archive is the read-back source for the publishing agent.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: read-artifact.sh [--project DIR] [--cat] <artifact-url | read-back-path | archive-path>

Resolve an artifact-sftp reference to its local archive. With no option, print the absolute
path on stdout. --cat streams the resolved artifact bytes instead. URLs must use the standard
/<tool>/<visibility>/<slug>/ artifact-sftp path; no URL is fetched.
EOF
}

fail() {
  local code=$1
  shift
  printf 'artifact-sftp-read: %s\n' "$*" >&2
  exit "$code"
}

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

candidate=''
if [[ "$reference" == http://* || "$reference" == https://* ]]; then
  url_remainder=${reference#*://}
  url_path="/${url_remainder#*/}"
  url_path=${url_path%%\?*}
  url_path=${url_path%%\#*}

  current_re='^/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/?$'
  index_re='^/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/index\.html$'
  snapshot_re='^/(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/([a-z0-9][a-z0-9-]{0,62})--([1-9][0-9]*)--([0-9]{8}T[0-9]{6}Z)\.html$'

  if [[ "$url_path" =~ $current_re ]]; then
    candidate="$project/docs/artifacts/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/${BASH_REMATCH[3]}/index.html"
  elif [[ "$url_path" =~ $index_re ]]; then
    candidate="$project/docs/artifacts/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/${BASH_REMATCH[3]}/index.html"
  elif [[ "$url_path" =~ $snapshot_re ]]; then
    [ "${BASH_REMATCH[3]}" = "${BASH_REMATCH[4]}" ] \
      || fail 2 "snapshot filename does not match its artifact slug"
    candidate="$project/docs/artifacts/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}/${BASH_REMATCH[3]}/${BASH_REMATCH[4]}--${BASH_REMATCH[5]}--${BASH_REMATCH[6]}.html"
  else
    fail 2 "not an artifact-sftp URL: $reference"
  fi
elif [[ "$reference" = /* ]]; then
  candidate=$reference
else
  candidate="$project/$reference"
fi

[ -f "$candidate" ] || fail 3 "local artifact archive is unavailable: $candidate (run from the publishing project or pass --project)"
[ ! -L "$candidate" ] || fail 3 "refusing symlinked artifact archive: $candidate"
parent=$(cd -P "$(dirname "$candidate")" && pwd)
resolved="$parent/$(basename "$candidate")"

archive_root="$project/docs/artifacts/"
case "$resolved" in
  "$archive_root"*) ;;
  *) fail 2 "resolved path is outside this project's docs/artifacts: $resolved" ;;
esac

archive_rel=${resolved#"$archive_root"}
archive_re='^(codex|openclaw|claude)/(private|public)/([a-z0-9][a-z0-9-]{0,62})/(index\.html|[a-z0-9][a-z0-9-]{0,62}--[1-9][0-9]*--[0-9]{8}T[0-9]{6}Z\.html)$'
[[ "$archive_rel" =~ $archive_re ]] \
  || fail 2 "path is not a valid artifact-sftp local archive: $resolved"
if [ "${BASH_REMATCH[4]}" != 'index.html' ]; then
  [ "${BASH_REMATCH[4]%%--*}" = "${BASH_REMATCH[3]}" ] \
    || fail 2 "snapshot filename does not match its artifact slug"
fi

if [ "$mode" = cat ]; then
  cat "$resolved"
else
  printf '%s\n' "$resolved"
fi
