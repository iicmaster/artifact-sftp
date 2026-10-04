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
export HOME="$WORK/home"
mkdir -p "$HOME"

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

drive_rc=0
bash "$READ" 'E:\nonexistent\drive\index.html' >"$WORK/out" 2>"$WORK/err" || drive_rc=$?
if [ "$drive_rc" -eq 3 ] \
  && grep -Fq 'unavailable: E:/nonexistent/drive/index.html' "$WORK/err" \
  && ! grep -Fq "$PROJECT/E:" "$WORK/err"; then
  echo "PASS windows drive reference is absolute with slashes normalized"
else
  echo "FAIL: windows drive reference handling — want exit 3 with a normalized absolute candidate"
  sed 's/^/  | /' "$WORK/err"; fails=$((fails+1))
fi

# Tier 2 success path: a remote fetch must emit its cache path through wpath()
# exactly like Tier 1 does. A stub sftp serves the fixture and a stub cygpath
# turns every -w call into a deterministic drive path, so the converted output
# is pinned here on any POSIX runner.
TIER2_FAKEBIN="$WORK/fakebin"
mkdir -p "$TIER2_FAKEBIN"
cat >"$TIER2_FAKEBIN/sftp" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
batch='' prev=''
for a in "$@"; do
  if [ "$prev" = '-b' ]; then batch=$a; fi
  prev=$a
done
[ -n "$batch" ] || exit 42
line=$(head -n1 "$batch")
case "$line" in
  get\ *)
    local_path=$(printf '%s' "$line" | sed -E 's/^get "[^"]*" "([^"]*)".*/\1/')
    cat "$TIER2_FIXTURE" > "$local_path"
    ;;
  *) exit 43 ;;
esac
STUB
cat >"$TIER2_FAKEBIN/cygpath" <<'STUB'
#!/usr/bin/env bash
printf 'E:\\fake%s\n' "$(printf '%s' "$2" | sed 's#/#\\#g')"
STUB
chmod 0755 "$TIER2_FAKEBIN/sftp" "$TIER2_FAKEBIN/cygpath"

TIER2_FIXTURE="$WORK/tier2-fixture.html"
printf 'tier 2 remote artifact bytes' > "$TIER2_FIXTURE"
TIER2_HOME="$WORK/tier2-home"
mkdir -p "$TIER2_HOME/.config/artifact-sftp"
: > "$TIER2_HOME/.config/artifact-sftp/known_hosts"
TIER2_CONFIG="$TIER2_HOME/.config/artifact-sftp/config"
printf 'SFTP_HOST=sftp.example\nSFTP_USER=tester\nREMOTE_DIR=/srv/artifacts\n' > "$TIER2_CONFIG"
chmod 0600 "$TIER2_CONFIG"

tier2_rc=0
tier2_got=$(env HOME="$TIER2_HOME" PATH="$TIER2_FAKEBIN:$PATH" TIER2_FIXTURE="$TIER2_FIXTURE" \
  bash "$READ" 'https://artifacts.example/codex/private/remote-doc/' 2>"$WORK/err") || tier2_rc=$?
tier2_want=$("$TIER2_FAKEBIN/cygpath" -w "$TIER2_HOME/.cache/artifact-sftp/remote/codex/private/remote-doc/index.html")
if [ "$tier2_rc" -eq 0 ] && [ "$tier2_got" = "$tier2_want" ]; then
  echo "PASS tier 2 remote fetch emits its cache path through wpath"
else
  echo "FAIL: tier 2 remote fetch — want '$tier2_want', got exit $tier2_rc '$tier2_got'"
  sed 's/^/  | /' "$WORK/err"; fails=$((fails+1))
fi

tier2_cat=$(env HOME="$TIER2_HOME" PATH="$TIER2_FAKEBIN:$PATH" TIER2_FIXTURE="$TIER2_FIXTURE" \
  bash "$READ" --cat 'https://artifacts.example/codex/private/remote-doc/' 2>"$WORK/err")
if [ "$tier2_cat" = 'tier 2 remote artifact bytes' ]; then
  echo "PASS tier 2 --cat streams raw bytes without the drive-path wrapper"
else
  echo "FAIL: tier 2 --cat must stream raw bytes — got '$tier2_cat'"
  sed 's/^/  | /' "$WORK/err"; fails=$((fails+1))
fi

if [ "$fails" -eq 0 ]; then
  echo "ALL CHECKS PASSED"
else
  exit 1
fi
