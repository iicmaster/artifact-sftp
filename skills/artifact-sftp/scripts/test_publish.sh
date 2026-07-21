#!/usr/bin/env bash
# Offline self-check for publish.sh — mocks sftp/curl via PATH shim; no network, no real config touched.
# Runs against a throwaway HOME so the real ~/.config/artifact-sftp is never read or written.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PUB="$SCRIPT_DIR/publish.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Sandbox HOME + mock bins
export HOME="$WORK/home"
mkdir -p "$HOME/.config/artifact-sftp" "$WORK/bin"
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
out='' hdr='' prev=''
for a in "$@"; do case "$prev" in -o) out=$a ;; -D) hdr=$a ;; esac; prev=$a; done
code="${MOCK_HTTP_CODE:-200}"
src="${MOCK_CURL_BODY:-${MOCK_LAST_PUT:?}}"
[ -n "$hdr" ] && { printf 'HTTP/2 %s \n' "$code" > "$hdr"; [ -n "${MOCK_LOCATION:-}" ] && printf 'location: %s\n' "$MOCK_LOCATION" >> "$hdr"; }
if [ -n "$out" ]; then cat "$src" > "$out"; else cat "$src"; fi
printf '%s' "$code"   # -w '%{http_code}'
EOF
chmod +x "$WORK/bin/sftp" "$WORK/bin/curl"
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
expect 2 "bad --tool rejected"                    -- bash "$PUB" --slug ok --tool claude "$good"

# --- secret scan ---
sec="$WORK/leak.html"
printf '<pre>-----BEGIN RSA PRIVATE KEY-----</pre>\n' > "$sec"
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

# --- happy path (mock sftp ok; private => HTTP verify skipped) ---
: > "$MOCK_LOG"
out=$(bash "$PUB" --slug ok "$good" 2>"$WORK/errout") || { echo "FAIL: happy path exited $?"; cat "$WORK/errout"; fails=$((fails+1)); }
[ "$out" = "https://example.invalid/codex/private/ok/" ] || { echo "FAIL: happy-path URL '$out'"; fails=$((fails+1)); }
grep -q 'index.html.tmp' "$MOCK_LOG" || { echo "FAIL: no atomic tmp upload in batch"; fails=$((fails+1)); }
grep -qxF 'codex/private/ok' "$HOME/.config/artifact-sftp/published.list" || { echo "FAIL: manifest not updated"; fails=$((fails+1)); }
echo "PASS happy path (atomic upload + manifest)"

# --- versioned snapshot + timestamp stamping ---
grep -qE 'ok--1--[0-9]{8}T[0-9]{6}Z\.html' "$MOCK_LOG" \
  && echo "PASS versioned snapshot name {slug}--{version}--{timestamp}" \
  || { echo "FAIL: versioned snapshot missing from batch"; fails=$((fails+1)); }
grep -q 'data-artifact-meta' "$MOCK_LAST_PUT" && grep -q 'created' "$MOCK_LAST_PUT" \
  && echo "PASS timestamp footer stamped into artifact" \
  || { echo "FAIL: timestamp footer not stamped"; fails=$((fails+1)); }

# --- public verify: hash match via mock curl (serves the stamped upload back) ---
unset MOCK_CURL_BODY
out=$(bash "$PUB" --slug ok2 --public "$good" 2>/dev/null)
[ "$out" = "https://example.invalid/codex/public/ok2/" ] && echo "PASS public verify (hash match)" || { echo "FAIL: public verify"; fails=$((fails+1)); }

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

# --- config-injection guard: a config value that SOURCES cleanly but is unsafe for the curl -K
#     config (embedded quote via bash $'...') must be rejected at read time, before any upload ---
cp "$cfg" "$cfg.pre-inj"
cat >> "$cfg" <<'INJ'
BASIC_AUTH=$'a:b"c'
INJ
expect 3 "unsafe BASIC_AUTH (quote via \$'') rejected"  -- bash "$PUB" --slug injtest "$good"
mv "$cfg.pre-inj" "$cfg"

# --- Cloudflare Access gate: private + basic-auth, server 302s to Access login -> graceful skip (exit 0, NOT 6) ---
echo 'BASIC_AUTH=viewer:secret' >> "$cfg"
export MOCK_HTTP_CODE=302 MOCK_LOCATION='https://team.cloudflareaccess.com/cdn-cgi/access/login/host'
unset MOCK_CURL_BODY
cfrc=0; out=$(bash "$PUB" --slug cfgate "$good" 2>"$WORK/errout") || cfrc=$?
if [ "$cfrc" -eq 0 ] && grep -q 'Cloudflare Access' "$WORK/errout"; then
  echo "PASS Cloudflare Access gate -> graceful skip (exit 0, not 6)"
else
  echo "FAIL: CF Access gate — want exit 0 + skip note, got exit $cfrc"; sed 's/^/  | /' "$WORK/errout"; fails=$((fails+1))
fi
unset MOCK_HTTP_CODE MOCK_LOCATION

echo
if [ "$fails" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "$fails CHECK(S) FAILED"; exit 1; fi
