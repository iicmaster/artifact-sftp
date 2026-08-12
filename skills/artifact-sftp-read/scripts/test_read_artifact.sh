#!/usr/bin/env bash
# Offline regression tests for the artifact-sftp local read-back resolver.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
READ="$SCRIPT_DIR/read-artifact.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

direct_rc=0
env -u ARTIFACT_SFTP_MCP_CALL bash "$READ" --help >"$WORK/direct.out" 2>"$WORK/direct.err" || direct_rc=$?
[ "$direct_rc" -eq 10 ] && grep -Fq 'Artifact SFTP MCP' "$WORK/direct.err" \
  && echo "PASS direct read resolver is rejected outside MCP" \
  || { echo "FAIL: direct read resolver bypass was not rejected" >&2; exit 1; }
export ARTIFACT_SFTP_MCP_CALL=1

PROJECT="$WORK/project"
mkdir -p "$PROJECT/docs/artifacts/codex/private/report"
PROJECT=$(cd -P "$PROJECT" && pwd)
CURRENT="$PROJECT/docs/artifacts/codex/private/report/index.html"
SNAPSHOT="$PROJECT/docs/artifacts/codex/private/report/report--2--20260810T120000Z.html"
printf 'current artifact bytes' > "$CURRENT"
printf 'snapshot artifact bytes' > "$SNAPSHOT"
printf 'outside archive' > "$WORK/outside.html"
ln -s "$CURRENT" "$PROJECT/docs/artifacts/codex/private/report/symlink.html"

cd "$PROJECT"
fails=0

expect_path() { # description reference expected-path
  local desc=$1 reference=$2 want=$3 got='' rc=0
  got=$(bash "$READ" "$reference" 2>"$WORK/err") || rc=$?
  if [ "$rc" -eq 0 ] && [ "$got" = "$want" ]; then
    echo "PASS $desc"
  else
    echo "FAIL: $desc — want '$want', got exit $rc '$got'"; sed 's/^/  | /' "$WORK/err"; fails=$((fails+1))
  fi
}

expect_exit() { # exit-code description -- command...
  local want=$1 desc=$2 got=0
  shift 3
  "$@" >"$WORK/out" 2>"$WORK/err" || got=$?
  if [ "$got" -eq "$want" ]; then
    echo "PASS ($want) $desc"
  else
    echo "FAIL: $desc — want exit $want, got $got"; sed 's/^/  | /' "$WORK/err"; fails=$((fails+1))
  fi
}

expect_path "canonical URL resolves current archive" \
  'https://artifacts.example/codex/private/report/' "$CURRENT"
expect_path "index URL with query and fragment resolves current archive" \
  'https://artifacts.example/codex/private/report/index.html?preview=1#top' "$CURRENT"
expect_path "versioned snapshot URL resolves immutable archive" \
  'https://artifacts.example/codex/private/report/report--2--20260810T120000Z.html' "$SNAPSHOT"
expect_path "read-back line resolves its exact archive" "read-back: $CURRENT" "$CURRENT"
expect_path "relative archive path resolves from project root" \
  'docs/artifacts/codex/private/report/index.html' "$CURRENT"

from_elsewhere='' outside_rc=0
from_elsewhere=$(cd "$WORK" && bash "$READ" --project "$PROJECT" \
  'https://artifacts.example/codex/private/report/' 2>"$WORK/err") || outside_rc=$?
if [ "$outside_rc" -eq 0 ] && [ "$from_elsewhere" = "$CURRENT" ]; then
  echo "PASS --project resolves an artifact outside the current directory"
else
  echo "FAIL: --project should resolve from the publishing project — got exit $outside_rc '$from_elsewhere'"
  sed 's/^/  | /' "$WORK/err"; fails=$((fails+1))
fi

content=$(bash "$READ" --cat 'https://artifacts.example/codex/private/report/' 2>"$WORK/err") || {
  echo "FAIL: --cat current artifact"; sed 's/^/  | /' "$WORK/err"; fails=$((fails+1));
}
[ "$content" = 'current artifact bytes' ] \
  && echo "PASS --cat streams resolved artifact bytes" \
  || { echo "FAIL: --cat did not stream current artifact bytes"; fails=$((fails+1)); }

expect_exit 2 "malformed URL is rejected without fetching it" -- \
  bash "$READ" 'https://artifacts.example/codex/private/../secret/'
expect_exit 2 "mismatched snapshot slug is rejected" -- \
  bash "$READ" 'https://artifacts.example/codex/private/report/other--2--20260810T120000Z.html'
expect_exit 3 "missing local archive is reported clearly" -- \
  bash "$READ" 'https://artifacts.example/codex/private/missing/'
expect_exit 2 "path outside local archive is rejected" -- bash "$READ" "$WORK/outside.html"
expect_exit 3 "symlinked archive is rejected" -- \
  bash "$READ" 'docs/artifacts/codex/private/report/symlink.html'

if [ "$fails" -eq 0 ]; then
  echo "ALL CHECKS PASSED"
else
  exit 1
fi
