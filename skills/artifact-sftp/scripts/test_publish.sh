#!/usr/bin/env bash
# Offline self-check for publish.sh — mocks sftp/curl via PATH shim; no network, no real config touched.
# Runs against a throwaway HOME so the real ~/.config/artifact-sftp is never read or written.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PUB="$SCRIPT_DIR/publish.sh"
HELPER="$SCRIPT_DIR/sftp_helper.py"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

direct_rc=0
env -u ARTIFACT_SFTP_MCP_CALL bash "$PUB" --help >"$WORK/direct.out" 2>"$WORK/direct.err" || direct_rc=$?
[ "$direct_rc" -eq 10 ] && grep -Fq 'Artifact SFTP MCP' "$WORK/direct.err" \
  && echo "PASS direct publish script is rejected outside MCP" \
  || { echo "FAIL: direct publish script bypass was not rejected" >&2; exit 1; }
direct_helper_rc=0
env -u ARTIFACT_SFTP_MCP_CALL python3 "$HELPER" >"$WORK/direct-helper.out" 2>"$WORK/direct-helper.err" || direct_helper_rc=$?
[ "$direct_helper_rc" -eq 10 ] && grep -Fq 'Artifact SFTP MCP' "$WORK/direct-helper.err" \
  && echo "PASS direct password transport is rejected outside MCP" \
  || { echo "FAIL: direct password transport bypass was not rejected" >&2; exit 1; }
export ARTIFACT_SFTP_MCP_CALL=1

# Sandbox HOME + mock bins
export HOME="$WORK/home"
mkdir -p "$HOME/.config/artifact-sftp" "$WORK/bin" "$WORK/project"
cat > "$WORK/bin/sftp" <<'EOF'
#!/usr/bin/env bash
batch='' prev=''
for a in "$@"; do [ "$prev" = "-b" ] && batch=$a; prev=$a; done
{ echo "mock-sftp $*"; [ -n "$batch" ] && cat "$batch"; } >> "${MOCK_LOG:?}"
if [ -n "$batch" ]; then
  # capture the last uploaded body (publish.sh stamps into a temp deleted on exit)
  src=$(sed -n 's/^put "\([^"]*\)".*/\1/p' "$batch" | tail -1)
  [ -n "$src" ] && cp "$src" "${MOCK_LAST_PUT:?}"
  # existence-check batch (first line "ls ..."): default = slug not found
  if head -n1 "$batch" | grep -q '^ls '; then
    exit "${MOCK_REMOTE_EXISTS_EXIT:-1}"
  fi
fi
exit "${MOCK_SFTP_EXIT:-0}"
EOF
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
# mock curl for publish.sh verify: honours -o <body> -D <hdr> -w '%{http_code}'.
out='' hdr='' prev='' url='' curl_q=0
for a in "$@"; do
  case "$prev" in -o) out=$a ;; -D) hdr=$a ;; esac
  [ "$a" = "-q" ] && curl_q=1
  prev=$a; url=$a
done
code="${MOCK_HTTP_CODE:-200}"
src="${MOCK_CURL_BODY:-${MOCK_LAST_PUT:?}}"
# publish.sh always pipes a -K config (possibly empty). An empty config on a /private/ URL is
# the unauthenticated probe, so the mock must answer it the way a protected host would —
# otherwise every private test would read as "exposed" and the exposure test could never fail
# for a real reason. MOCK_ANON_EXPOSED=1 simulates a host that forgot to protect every path;
# MOCK_ANON_EXPOSED_TARGET= index or snapshot limits the exposure to one uploaded URL.
cfgin=''; [ -t 0 ] || cfgin=$(cat)
case "$url" in
  */private/*)
    if [ -z "$cfgin" ]; then
      exposed=0
      # A curlrc with credentials is ambient auth unless curl is invoked with -q.
      [ "${MOCK_CURLRC_AUTH:-0}" = 1 ] && [ "$curl_q" -eq 0 ] && exposed=1
      case "${MOCK_ANON_EXPOSED_TARGET:-}" in
        index) case "$url" in */index.html\?*) exposed=1 ;; esac ;;
        snapshot) case "$url" in *--*.html\?*) exposed=1 ;; esac ;;
      esac
      [ "${MOCK_ANON_EXPOSED:-0}" = 1 ] && exposed=1
      if [ "$exposed" -eq 0 ]; then
        code="${MOCK_ANON_CODE:-403}"
        [ -n "$hdr" ] && printf 'HTTP/2 %s \n' "$code" > "$hdr"
        printf '%s' "$code"; exit 0
      fi
    fi
    ;;
esac
[ -n "$hdr" ] && { printf 'HTTP/2 %s \n' "$code" > "$hdr"; [ -n "${MOCK_LOCATION:-}" ] && printf 'location: %s\n' "$MOCK_LOCATION" >> "$hdr"; }
if [ -n "$out" ]; then cat "$src" > "$out"; else cat "$src"; fi
printf '%s' "$code"   # -w '%{http_code}'
EOF
chmod +x "$WORK/bin/sftp" "$WORK/bin/curl"
cat > "$WORK/bin/op.exe" <<'EOF'
#!/bin/sh
[ "${1:-}" = read ] || exit 2
printf '%s\n' 'offline-op-private-key-fixture'
EOF
chmod +x "$WORK/bin/op.exe"
export PATH="$WORK/bin:$PATH"
export MOCK_LOG="$WORK/sftp.log"
export MOCK_LAST_PUT="$WORK/last_put"

cfg="$HOME/.config/artifact-sftp/config"
cat > "$cfg" <<'EOF'
SFTP_HOST=example.invalid
SFTP_USER=artifacts
REMOTE_DIR=domains/example.invalid/public_html
PUBLIC_BASE_URL=https://example.invalid
DEFAULT_TOOL=codex
SSH_KEY=/dev/null
EOF
chmod 600 "$cfg"
touch "$HOME/.config/artifact-sftp/known_hosts"

good="$WORK/page.html"
printf '<title>t</title><p>hello</p>\n' > "$good"

# The publisher archives relative to the caller's project working directory.
cd "$WORK/project"

fails=0
expect() { # expect <exit-code> <desc> -- cmd...
  local want=$1 desc=$2; shift 3
  local got=0
  "$@" >"$WORK/out" 2>"$WORK/errout" || got=$?
  if [ "$got" -eq "$want" ]; then
    echo "PASS ($want) $desc"
  else
    echo "FAIL: $desc — want exit $want, got $got"; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
  fi
}

# --- slug validation ---
expect 2 "slug with path traversal rejected"      -- bash "$PUB" --slug '../evil' "$good"
expect 2 "slug with uppercase rejected"           -- bash "$PUB" --slug 'Evil' "$good"
expect 2 "slug 64+ chars rejected"                -- bash "$PUB" --slug "$(printf 'a%.0s' {1..64})" "$good"
expect 2 "missing slug rejected"                  -- bash "$PUB" "$good"

# --- input validation ---
printf 'md' > "$WORK/nope.md"
expect 2 "non-html extension rejected"            -- bash "$PUB" --slug ok "$WORK/nope.md"
printf 'x' > "$WORK/real.html"; ln -s "$WORK/real.html" "$WORK/link.html"
expect 2 "symlink rejected"                       -- bash "$PUB" --slug ok "$WORK/link.html"
expect 2 "bad --tool rejected"                    -- bash "$PUB" --slug ok --tool bogus "$good"

# --- secret scan ---
sec="$WORK/leak.html"
printf '<pre>-----BEGIN %s PRIVATE KEY-----</pre>\n' 'RSA' > "$sec"
expect 4 "PEM private key blocked"                -- bash "$PUB" --slug ok "$sec"
# fixture assembled at runtime so repo pre-commit secret scanners don't flag this file
printf '<p>%s%s</p>\n' 'AKIA' 'ABCDEFGHIJKLMNOP' > "$sec"
expect 4 "AWS key blocked"                        -- bash "$PUB" --slug ok "$sec"
printf '<p>see op://vault/item</p>\n' > "$sec"
expect 4 "op:// reference blocked"                -- bash "$PUB" --slug ok "$sec"

# --- dry-run prints URL as last stdout line ---
out=$(bash "$PUB" --slug ok --dry-run "$good" 2>/dev/null)
if [ "$out" = "https://example.invalid/codex/private/ok/" ]; then
  echo "PASS dry-run URL contract"
else
  echo "FAIL: dry-run URL contract — got '$out'"; fails=$((fails+1))
fi
[ ! -e "$WORK/project/docs/artifacts" ] \
  && echo "PASS dry-run does not create local archive" \
  || { echo "FAIL: dry-run created local archive"; fails=$((fails+1)); }

# --- happy path (mock sftp ok; private => HTTP verify skipped) ---
: > "$MOCK_LOG"
out=$(bash "$PUB" --slug ok "$good" 2>"$WORK/errout") || { echo "FAIL: happy path exited $?"; cat "$WORK/errout"; fails=$((fails+1)); }
[ "$out" = "https://example.invalid/codex/private/ok/" ] || { echo "FAIL: happy-path URL '$out'"; fails=$((fails+1)); }
grep -q 'index.html.tmp' "$MOCK_LOG" || { echo "FAIL: no atomic tmp upload in batch"; fails=$((fails+1)); }
grep -qxF 'codex/private/ok' "$HOME/.config/artifact-sftp/published.list" || { echo "FAIL: manifest not updated"; fails=$((fails+1)); }
echo "PASS happy path (atomic upload + manifest)"
cp "$MOCK_LAST_PUT" "$WORK/happy-last-put"

# 1Password resolution must work when only op.exe is available on PATH (the
# WSL/native-Windows case). Build an isolated PATH with no directory containing
# op, while retaining the small set of host utilities publish.sh needs.
OP_ONLY_BIN="$WORK/op-only-bin"
mkdir -p "$OP_ONLY_BIN"
for command_name in awk bash cat chmod cp date grep head mkdir mktemp mv perl rm sed sort stat tail tr; do
  command_path=$(command -v "$command_name" || true)
  [ -n "$command_path" ] && ln -sf "$command_path" "$OP_ONLY_BIN/$command_name"
done
SAFE_PATH=''
old_ifs=$IFS; IFS=:
for path_dir in $PATH; do
  [ -n "$path_dir" ] || continue
  [ -x "$path_dir/op" ] && continue
  SAFE_PATH="${SAFE_PATH:+$SAFE_PATH:}$path_dir"
done
IFS=$old_ifs
OP_ONLY_PATH="$OP_ONLY_BIN:$WORK/bin:$SAFE_PATH"
if env PATH="$OP_ONLY_PATH" /bin/bash -c 'command -v op >/dev/null 2>&1'; then
  echo "FAIL: op-only PATH unexpectedly contains op"; fails=$((fails+1))
fi
cp "$cfg" "$cfg.before-op"
awk '!/^SSH_KEY=/' "$cfg.before-op" >"$cfg"
printf '%s\n' 'OP_KEY_REF=op://vault/item' >>"$cfg"
chmod 600 "$cfg"
op_only_rc=0
op_only_out=''
op_only_out=$(env PATH="$OP_ONLY_PATH" /bin/bash "$PUB" --slug op-only --force "$good" 2>"$WORK/op-only.err") \
  || op_only_rc=$?
if [ "$op_only_rc" -eq 0 ] && [ "$op_only_out" = 'https://example.invalid/codex/private/op-only/' ]; then
  echo "PASS op.exe-only PATH resolves 1Password key"
else
  echo "FAIL: op.exe-only PATH publish — want exit 0 + URL, got exit $op_only_rc '$op_only_out'"
  sed 's/^/  | /' "$WORK/op-only.err"; fails=$((fails+1))
fi
mv "$cfg.before-op" "$cfg"
chmod 600 "$cfg"
cp "$WORK/happy-last-put" "$MOCK_LAST_PUT"

# --- versioned snapshot + timestamp stamping ---
grep -qE 'ok--1--[0-9]{8}T[0-9]{6}Z\.html' "$MOCK_LOG" \
  && echo "PASS versioned snapshot name {slug}--{version}--{timestamp}" \
  || { echo "FAIL: versioned snapshot missing from batch"; fails=$((fails+1)); }
grep -q 'data-artifact-meta' "$MOCK_LAST_PUT" && grep -q 'created' "$MOCK_LAST_PUT" \
  && echo "PASS timestamp footer stamped into artifact" \
  || { echo "FAIL: timestamp footer not stamped"; fails=$((fails+1)); }
# The source (no head/html) must still get a UTF-8 declaration before the readable footer.
grep -q '<head>' "$MOCK_LAST_PUT" && grep -q '<meta charset="utf-8">' "$MOCK_LAST_PUT" \
  && echo "PASS UTF-8 charset declared when source has no head" \
  || { echo "FAIL: UTF-8 charset not injected"; fails=$((fails+1)); }
grep -Fq 'https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700&display=swap' "$MOCK_LAST_PUT" \
  && grep -Fq 'data-artifact-sftp-font="sarabun"' "$MOCK_LAST_PUT" \
  && grep -Fq 'font-family:"Sarabun","Noto Sans Thai",system-ui,sans-serif' "$MOCK_LAST_PUT" \
  && echo "PASS Sarabun is injected as the default Thai font" \
  || { echo "FAIL: Sarabun default font was not injected"; fails=$((fails+1)); }
grep -qE 'created [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} +(ICT|UTC|\+[0-9]{2})' "$MOCK_LAST_PUT" \
  && echo "PASS footer time in configured timezone" \
  || { echo "FAIL: footer timezone missing"; fails=$((fails+1)); }

# --- mandatory local archive ---
LOCAL_OK="$WORK/project/docs/artifacts/codex/private/ok"
[ -f "$LOCAL_OK/index.html" ] && echo "PASS local current copy in docs/artifacts" \
  || { echo "FAIL: local current copy missing"; fails=$((fails+1)); }
local_snapshot=$(find "$LOCAL_OK" -maxdepth 1 -type f -name 'ok--1--*.html' -print -quit)
[ -n "$local_snapshot" ] && cmp -s "$local_snapshot" "$MOCK_LAST_PUT" \
  && echo "PASS local versioned snapshot matches uploaded bytes" \
  || { echo "FAIL: local snapshot missing or mismatched"; fails=$((fails+1)); }
grep -q 'read-back: .*docs/artifacts/codex/private/ok/index.html' "$WORK/errout" \
  && echo "PASS read-back path reported on stderr" \
  || { echo "FAIL: read-back path not reported"; fails=$((fails+1)); }

# --- public verify: hash match via mock curl (serves the stamped upload back) ---
unset MOCK_CURL_BODY
out=$(bash "$PUB" --slug ok2 --public "$good" 2>/dev/null)
[ "$out" = "https://example.invalid/codex/public/ok2/" ] && echo "PASS public verify (hash match)" || { echo "FAIL: public verify"; fails=$((fails+1)); }
[ -f "$WORK/project/docs/artifacts/codex/public/ok2/index.html" ] \
  && echo "PASS public publish also archives locally" \
  || { echo "FAIL: public local archive missing"; fails=$((fails+1)); }

# --- public verify: hash mismatch => exit 6 ---
printf 'tampered' > "$WORK/other.html"; export MOCK_CURL_BODY="$WORK/other.html"
expect 6 "public verify detects content mismatch"  -- bash "$PUB" --slug ok3 --public "$good"

# --- upload failure => exit 5 ---
export MOCK_SFTP_EXIT=1 MOCK_CURL_BODY="$good"
expect 5 "sftp failure surfaces as exit 5"         -- bash "$PUB" --slug ok4 --force "$good"
unset MOCK_SFTP_EXIT

# --- config guards ---
chmod 644 "$cfg"
expect 3 "world-readable config rejected"          -- bash "$PUB" --slug ok "$good"
chmod 600 "$cfg"

cp "$cfg" "$cfg.before-invalid-url"
sed 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=https://example.invalid/#' \
  "$cfg.before-invalid-url" >"$cfg"
chmod 600 "$cfg"
expect 3 "trailing slash in PUBLIC_BASE_URL rejected" -- bash "$PUB" --slug bad-url "$good"
mv "$cfg.before-invalid-url" "$cfg"
chmod 600 "$cfg"

cp "$cfg" "$cfg.before-query-url"
sed 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=https://example.invalid/artifacts?preview=1#' \
  "$cfg.before-query-url" >"$cfg"
chmod 600 "$cfg"
expect 3 "query in PUBLIC_BASE_URL rejected" -- bash "$PUB" --slug query-url "$good"
mv "$cfg.before-query-url" "$cfg"
chmod 600 "$cfg"

cp "$cfg" "$cfg.before-path-url"
sed 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=https://example.invalid/artifacts#' \
  "$cfg.before-path-url" >"$cfg"
chmod 600 "$cfg"
expect 3 "path in PUBLIC_BASE_URL rejected" -- bash "$PUB" --slug path-url "$good"
mv "$cfg.before-path-url" "$cfg"
chmod 600 "$cfg"

# --- config-injection guard: a config value that SOURCES cleanly but is unsafe for the curl -K
#     config (embedded quote via bash $'...') must be rejected at read time, before any upload ---
cp "$cfg" "$cfg.pre-inj"
cat >> "$cfg" <<'INJ'
CF_ACCESS_CLIENT_SECRET=$'a:b"c'
INJ
expect 3 "unsafe CF_ACCESS_CLIENT_SECRET (quote via \$'') rejected"  -- bash "$PUB" --slug injtest "$good"
mv "$cfg.pre-inj" "$cfg"

# --- Cloudflare Access gate: private + service token, server 302s to Access login -> graceful skip (exit 0, NOT 6) ---
echo 'CF_ACCESS_CLIENT_ID=zzz' >> "$cfg"
echo 'CF_ACCESS_CLIENT_SECRET=yyy' >> "$cfg"
export MOCK_HTTP_CODE=302 MOCK_LOCATION='https://team.cloudflareaccess.com/cdn-cgi/access/login/host'
unset MOCK_CURL_BODY
cfrc=0; out=$(bash "$PUB" --slug cfgate "$good" 2>"$WORK/errout") || cfrc=$?
if [ "$cfrc" -eq 0 ] && grep -q 'Cloudflare Access' "$WORK/errout"; then
  echo "PASS Cloudflare Access gate -> graceful skip (exit 0, not 6)"
else
  echo "FAIL: CF Access gate — want exit 0 + skip note, got exit $cfrc"; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
unset MOCK_HTTP_CODE MOCK_LOCATION

# --- encoding/language stamping on a full document; DEFAULT_LANG / DEFAULT_TIMEZONE ---
printf '<!DOCTYPE html>\n<html><head><title>t</title></head><body><p>hello</p></body></html>\n' > "$WORK/stamp.html"
cp "$cfg" "$cfg.pre-stamp"
printf 'DEFAULT_LANG=en\nDEFAULT_TIMEZONE=UTC\n' >> "$cfg"
stamprc=0; bash "$PUB" --slug stamp "$WORK/stamp.html" >"$WORK/out" 2>"$WORK/errout" || stamprc=$?
STAMPED_COPY="$WORK/project/docs/artifacts/codex/private/stamp/index.html"
if [ "$stamprc" -eq 0 ] && grep -q '<html lang="en"' "$STAMPED_COPY" \
    && grep -q '<meta charset="utf-8">' "$STAMPED_COPY" \
    && grep -qE 'created [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} UTC' "$STAMPED_COPY"; then
  echo "PASS lang + charset + timezone follow DEFAULT_LANG / DEFAULT_TIMEZONE"
else
  echo "FAIL: stamping config — want lang=en + charset + UTC footer, got exit $stamprc"
  sed 's/^/  | /' "$STAMPED_COPY" 2>/dev/null; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
mv "$cfg.pre-stamp" "$cfg"

# --- HTML tag names are case-insensitive: uppercase tags still receive every stamp ---
printf '%s\n' '<!DOCTYPE html><HTML><HEAD><TITLE>t</TITLE></HEAD><BODY><p>uppercase</p></BODY></HTML>' > "$WORK/uppercase-tags.html"
uppercaserc=0; bash "$PUB" --slug uppercase-tags "$WORK/uppercase-tags.html" >"$WORK/out" 2>"$WORK/errout" || uppercaserc=$?
UPPERCASE_COPY="$WORK/project/docs/artifacts/codex/private/uppercase-tags/index.html"
if [ "$uppercaserc" -eq 0 ] \
    && grep -Fq '<HTML lang="th"' "$UPPERCASE_COPY" \
    && grep -Fq '<meta charset="utf-8">' "$UPPERCASE_COPY" \
    && grep -Fq 'data-artifact-sftp-font="sarabun"' "$UPPERCASE_COPY" \
    && grep -Fq '</footer></BODY>' "$UPPERCASE_COPY"; then
  echo "PASS uppercase HTML tags receive lang, charset, Sarabun, and footer stamps"
else
  echo "FAIL: uppercase HTML tags were not fully stamped (exit $uppercaserc)"; sed 's/^/  | /' "$UPPERCASE_COPY" 2>/dev/null; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi

# --- a source that already declares the publisher marker must not receive a duplicate font link ---
printf '%s\n' '<!DOCTYPE html><html><head><style data-artifact-sftp-font="sarabun">html{font-family:"Sarabun"}</style></head><body><p>once</p></body></html>' > "$WORK/sarabun-once.html"
sarabunrc=0; bash "$PUB" --slug sarabun-once "$WORK/sarabun-once.html" >"$WORK/out" 2>"$WORK/errout" || sarabunrc=$?
SARABUN_COPY="$WORK/project/docs/artifacts/codex/private/sarabun-once/index.html"
sarabun_markers=$(grep -o 'data-artifact-sftp-font="sarabun"' "$SARABUN_COPY" 2>/dev/null | wc -l | tr -d ' ')
if [ "$sarabunrc" -eq 0 ] && [ "$sarabun_markers" -eq 1 ]; then
  echo "PASS Sarabun marker is idempotent on republishable source"
else
  echo "FAIL: Sarabun marker was duplicated or publish failed (exit $sarabunrc)"; sed 's/^/  | /' "$SARABUN_COPY" 2>/dev/null; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi

# --- footer must target the final </body>, not an inlined JavaScript string ---
printf '%s\n' '<!DOCTYPE html><html><head><title>t</title></head><body><script>const fragment = "<body>x</body></html>";</script></body></html>' > "$WORK/inline-body.html"
inlinebodyrc=0; bash "$PUB" --slug inline-body "$WORK/inline-body.html" >"$WORK/out" 2>"$WORK/errout" || inlinebodyrc=$?
INLINE_BODY_COPY="$WORK/project/docs/artifacts/codex/private/inline-body/index.html"
if [ "$inlinebodyrc" -eq 0 ] \
    && grep -Fq '<script>const fragment = "<body>x</body></html>";</script>' "$INLINE_BODY_COPY" \
    && grep -Fq '</script><footer data-artifact-meta' "$INLINE_BODY_COPY" \
    && grep -Fq '</footer></body></html>' "$INLINE_BODY_COPY"; then
  echo "PASS footer stamps the final body tag, outside inline JavaScript"
else
  echo "FAIL: footer must stamp the final body tag without changing inline JavaScript"
  sed 's/^/  | /' "$INLINE_BODY_COPY" 2>/dev/null; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi

# --- private that the host serves to anyone => exit 7, and never print a URL ---
# The failure this guards against: the upload works, the authenticated verify passes, and the
# script then announces "private" for a path that never required a credential.
export MOCK_ANON_EXPOSED=1
unset MOCK_CURL_BODY
exprc=0; bash "$PUB" --slug exposed "$good" >"$WORK/out" 2>"$WORK/errout" || exprc=$?
if [ "$exprc" -eq 7 ] && grep -q 'EXPOSED' "$WORK/errout" \
    && ! grep -q 'https://' "$WORK/out" && ! grep -q 'https://' "$WORK/errout"; then
  echo "PASS unprotected private path -> exit 7, no URL printed"
else
  echo "FAIL: unprotected private path — want exit 7 + EXPOSED on stderr + no URL on stdout, got exit $exprc"
  sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
unset MOCK_ANON_EXPOSED

# --- only the versioned snapshot is exposed => exit 7 ---
export MOCK_ANON_EXPOSED_TARGET=snapshot
snaprc=0; bash "$PUB" --slug exposed-snapshot "$good" >"$WORK/out" 2>"$WORK/errout" || snaprc=$?
if [ "$snaprc" -eq 7 ] && grep -q 'versioned snapshot' "$WORK/errout" \
    && ! grep -q 'https://' "$WORK/out" && ! grep -q 'https://' "$WORK/errout"; then
  echo "PASS exposed versioned snapshot -> exit 7, no URL printed"
else
  echo "FAIL: exposed versioned snapshot — want exit 7 + no URL, got exit $snaprc"
  sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
unset MOCK_ANON_EXPOSED_TARGET

# --- an inconclusive anonymous probe => exit 8, and withhold the URL ---
export MOCK_ANON_CODE=503
unknownrc=0; bash "$PUB" --slug inconclusive "$good" >"$WORK/out" 2>"$WORK/errout" || unknownrc=$?
if [ "$unknownrc" -eq 8 ] && grep -q 'inconclusive' "$WORK/errout" \
    && ! grep -q 'https://' "$WORK/out"; then
  echo "PASS inconclusive private probe -> exit 8, no URL printed"
else
  echo "FAIL: inconclusive private probe — want exit 8 + no URL, got exit $unknownrc"
  sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
unset MOCK_ANON_CODE

# --- ambient curlrc credentials must not affect the anonymous probe ---
export MOCK_CURLRC_AUTH=1
curlrcrc=0; out=$(bash "$PUB" --slug curlrc-protected "$good" 2>"$WORK/errout") || curlrcrc=$?
if [ "$curlrcrc" -eq 0 ] && [ "$out" = "https://example.invalid/codex/private/curlrc-protected/" ] \
    && ! grep -q 'EXPOSED' "$WORK/errout"; then
  echo "PASS anonymous probe ignores ambient curlrc credentials"
else
  echo "FAIL: ambient curlrc credentials changed privacy result — got exit $curlrcrc '$out'"
  sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
unset MOCK_CURLRC_AUTH

# --- protected private path still succeeds (the guard must not cry wolf) ---
protrc=0; out=$(bash "$PUB" --slug protok "$good" 2>"$WORK/errout") || protrc=$?
if [ "$protrc" -eq 0 ] && [ "$out" = "https://example.invalid/codex/private/protok/" ]; then
  echo "PASS protected private path still publishes (exit 0)"
else
  echo "FAIL: protected private path — want exit 0 + URL, got exit $protrc '$out'"
  sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi

# --- local archive is a hard gate and happens before upload ---
mkdir -p "$WORK/failing-project/docs/artifacts/codex/private"
ln -s "$WORK" "$WORK/failing-project/docs/artifacts/codex/private/blocked"
puts_before=$(grep -c '^put ' "$MOCK_LOG" || true)
archive_rc=0
(cd "$WORK/failing-project" && bash "$PUB" --slug blocked "$good" >"$WORK/out" 2>"$WORK/errout") || archive_rc=$?
puts_after=$(grep -c '^put ' "$MOCK_LOG" || true)
if [ "$archive_rc" -eq 9 ] && grep -q 'must not be a symlink' "$WORK/errout" \
    && [ "$puts_after" -eq "$puts_before" ]; then
  echo "PASS local archive failure blocks SFTP upload (exit 9)"
else
  echo "FAIL: local archive gate — want exit 9 with no upload, got exit $archive_rc"
  sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi

# --- delete is idempotent and ignores missing directory ---
del_rc=0
bash "$PUB" --delete nonexistent-slug >"$WORK/out" 2>"$WORK/del_errout" || del_rc=$?
if [ "$del_rc" -eq 0 ] && grep -q 'deleted: codex/private/nonexistent-slug' "$WORK/del_errout"; then
  echo "PASS idempotent delete of non-existent slug succeeds (exit 0)"
else
  echo "FAIL: idempotent delete of non-existent slug failed — got exit $del_rc"
  sed 's/^/  | /' "$WORK/del_errout"; fails=$((fails+1))
fi

# --- delete operates without validating PUBLIC_BASE_URL ---
cp "$cfg" "$cfg.before-del-bad-url"
sed 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=https://example.invalid/bad/path/#' "$cfg.before-del-bad-url" >"$cfg"
chmod 600 "$cfg"
del_bad_url_rc=0
bash "$PUB" --delete del-with-bad-url >"$WORK/out" 2>"$WORK/del_bad_url.err" || del_bad_url_rc=$?
if [ "$del_bad_url_rc" -eq 0 ] && grep -q 'deleted: codex/private/del-with-bad-url' "$WORK/del_bad_url.err"; then
  echo "PASS delete succeeds even with invalid PUBLIC_BASE_URL"
else
  echo "FAIL: delete failed when PUBLIC_BASE_URL had a path — got exit $del_bad_url_rc"
  sed 's/^/  | /' "$WORK/del_bad_url.err"; fails=$((fails+1))
fi
mv "$cfg.before-del-bad-url" "$cfg"
chmod 600 "$cfg"

echo
if [ "$fails" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "$fails CHECK(S) FAILED"; exit 1; fi
