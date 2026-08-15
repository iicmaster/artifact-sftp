#!/usr/bin/env bash
# Offline regression tests for setup.sh. Every test uses an isolated HOME and a
# mocked ssh-keyscan, so this script never reads or changes the machine's real
# artifact-sftp configuration and never contacts an SFTP server.
set -euo pipefail
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SETUP_SOURCE="$SCRIPT_DIR/setup.sh"
WIZARD_SOURCE="$SCRIPT_DIR/../../artifact-sftp-setup/scripts/setup-wizard.sh"
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/artifact-sftp-setup-test.XXXXXX")

cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_rc() {
  [ "$RUN_RC" -eq "$1" ] || fail "$2 (expected exit $1, got $RUN_RC)"
}

assert_contains() {
  grep -Fq -- "$2" "$1" || fail "$3"
}

assert_not_contains() {
  if grep -Fq -- "$2" "$1"; then
    fail "$3"
  fi
}

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

write_known_host() {
  local destination=$1 host=$2 port=$3 known_label=$2
  [ "$port" = 22 ] || known_label="[$host]:$port"
  printf '%s %s\n' "$known_label" "$HOST_KEY_BLOB" >"$destination"
  chmod 600 "$destination"
}

run_capture() {
  local output_file=$1
  shift
  set +e
  "$@" >"$output_file" 2>&1
  RUN_RC=$?
  set -e
}

run_from_dir_capture() {
  local output_file=$1
  local working_dir=$2
  shift 2
  set +e
  (cd "$working_dir" && "$@") >"$output_file" 2>&1
  RUN_RC=$?
  set -e
}

[ -f "$SETUP_SOURCE" ] || fail "setup.sh not found beside this test"
[ -f "$WIZARD_SOURCE" ] || fail "setup wizard not found in the sibling setup skill"

direct_rc=0
env -u ARTIFACT_SFTP_MCP_CALL bash "$SETUP_SOURCE" --status >"$TMP_ROOT/direct.out" 2>"$TMP_ROOT/direct.err" || direct_rc=$?
[ "$direct_rc" -eq 10 ] && grep -Fq 'Artifact SFTP MCP' "$TMP_ROOT/direct.err" \
  || fail "direct setup script bypass was not rejected"
wizard_direct_rc=0
env -u ARTIFACT_SFTP_MCP_CALL bash "$WIZARD_SOURCE" --status >"$TMP_ROOT/wizard-direct.out" 2>"$TMP_ROOT/wizard-direct.err" || wizard_direct_rc=$?
[ "$wizard_direct_rc" -eq 10 ] && grep -Fq 'Artifact SFTP MCP' "$TMP_ROOT/wizard-direct.err" \
  || fail "direct setup wizard bypass was not rejected"
export ARTIFACT_SFTP_MCP_CALL=1

# Supply only the external capabilities setup.sh checks. ssh-keyscan returns a
# deterministic test-only public host key instead of opening the network.
MOCK_BIN="$TMP_ROOT/mock-bin"
mkdir -p "$MOCK_BIN"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'port=22' \
  'host=test.invalid' \
  'while [ "$#" -gt 0 ]; do' \
  '  case "$1" in' \
  '    -p) port=$2; shift 2 ;;' \
  '    *) host=$1; shift ;;' \
  '  esac' \
  'done' \
  'printf "[%s]:%s ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOfflineFixtureOnly\\n" "$host" "$port"' \
  >"$MOCK_BIN/ssh-keyscan"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$MOCK_BIN/sftp"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$MOCK_BIN/curl"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$MOCK_BIN/sha256sum"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$MOCK_BIN/python3"
chmod 700 "$MOCK_BIN/ssh-keyscan" "$MOCK_BIN/sftp" "$MOCK_BIN/curl" "$MOCK_BIN/sha256sum" "$MOCK_BIN/python3"
TEST_PATH="$MOCK_BIN:$PATH"

# Generate a temporary, valid public key so ssh-keygen can validate every
# known_hosts fixture without committing private-key material.
HOST_KEY_FILE="$TMP_ROOT/fixture-host-key"
ssh-keygen -q -t ed25519 -N '' -f "$HOST_KEY_FILE" >/dev/null
HOST_KEY_BLOB=$(awk '{ print $1 " " $2 }' "$HOST_KEY_FILE.pub")

# Exercise both an unrelated current directory and a setup.sh path containing
# spaces. The copied script is the exact source under test.
SPACED_PLUGIN="$TMP_ROOT/plugin with spaces"
SPACED_SCRIPT_DIR="$SPACED_PLUGIN/skills/artifact-sftp/scripts"
UNRELATED_CWD="$TMP_ROOT/unrelated working directory"
mkdir -p "$SPACED_SCRIPT_DIR" "$UNRELATED_CWD"
cp "$SETUP_SOURCE" "$SPACED_SCRIPT_DIR/setup.sh"
chmod 700 "$SPACED_SCRIPT_DIR/setup.sh"
SETUP="$SPACED_SCRIPT_DIR/setup.sh"

# --status must be observational: an empty HOME remains empty and reports the
# documented not-ready exit code.
EMPTY_HOME="$TMP_ROOT/empty home"
mkdir -p "$EMPTY_HOME"
STATUS_EMPTY_OUT="$TMP_ROOT/status-empty.out"
run_from_dir_capture "$STATUS_EMPTY_OUT" "$UNRELATED_CWD" \
  env HOME="$EMPTY_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 3 "status should report an unconfigured HOME"
assert_contains "$STATUS_EMPTY_OUT" 'config: missing' "missing config was not reported"
assert_contains "$STATUS_EMPTY_OUT" 'NOT READY' "not-ready summary was not reported"
[ -z "$(find "$EMPTY_HOME" -mindepth 1 -print -quit)" ] \
  || fail "--status wrote files into an empty HOME"

# First setup: key authentication, stdin-only optional secret, mocked host-key
# pinning, and a HOME whose path contains spaces.
CONFIG_HOME="$TMP_ROOT/configured home"
KEY_FILE="$TMP_ROOT/test_key"
printf '%s\n' 'offline-private-key-placeholder' >"$KEY_FILE"
chmod 600 "$KEY_FILE"
FIRST_KNOWN_SOURCE="$TMP_ROOT/first-preverified-known-hosts"
write_known_host "$FIRST_KNOWN_SOURCE" sftp.test.invalid 2222

UNCONFIRMED_HOME="$TMP_ROOT/unconfirmed host home"
UNCONFIRMED_OUT="$TMP_ROOT/unconfirmed-host.out"
run_capture "$UNCONFIRMED_OUT" env HOME="$UNCONFIRMED_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host sftp.test.invalid \
  --user artifact-user \
  --port 2222 \
  --remote-dir /files \
  --url https://artifacts.test.invalid \
  --tool codex \
  --ssh-key "$KEY_FILE"
assert_rc 2 "non-interactive setup should require a preverified host-key file"
assert_contains "$UNCONFIRMED_OUT" '--known-hosts-file is required' \
  "missing preverified host-key refusal was not explained"
[ ! -e "$UNCONFIRMED_HOME/.config/artifact-sftp/config" ] \
  || fail "unconfirmed host setup wrote a config"

# URL construction is strict: setup must reject a trailing slash before it can
# write a config, otherwise publish would produce a double slash in every URL.
INVALID_URL_HOME="$TMP_ROOT/invalid url home"
INVALID_URL_OUT="$TMP_ROOT/invalid-url.out"
run_capture "$INVALID_URL_OUT" env HOME="$INVALID_URL_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host sftp.test.invalid \
  --user artifact-user \
  --port 2222 \
  --remote-dir /files \
  --url https://artifacts.test.invalid/ \
  --tool codex \
  --ssh-key "$KEY_FILE" \
  --known-hosts-file "$FIRST_KNOWN_SOURCE"
assert_rc 2 "setup should reject a trailing slash in PUBLIC_BASE_URL"
assert_contains "$INVALID_URL_OUT" 'HTTPS origin with a host, no path/query/fragment, and no trailing slash' \
  "invalid PUBLIC_BASE_URL refusal was not explained"
[ ! -e "$INVALID_URL_HOME/.config/artifact-sftp/config" ] \
  || fail "invalid PUBLIC_BASE_URL setup wrote a config"

CF_ID='fixture-cf-client-id'
CF_SECRET='fixture-cf-secret-redact-me'  # pragma: allowlist secret
SECRET_INPUT="$TMP_ROOT/setup.stdin"
printf '%s\n' "$CF_SECRET" >"$SECRET_INPUT"
FIRST_OUT="$TMP_ROOT/first-setup.out"
run_from_dir_capture "$FIRST_OUT" "$UNRELATED_CWD" \
  env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" \
    --host sftp.test.invalid \
    --user artifact-user \
    --port 2222 \
    --remote-dir /files \
    --url https://artifacts.test.invalid \
    --tool codex \
    --cf-access-id "$CF_ID" \
    --cf-access-secret - \
    --lang th \
    --timezone Asia/Bangkok \
    --ssh-key "$KEY_FILE" \
    --known-hosts-file "$FIRST_KNOWN_SOURCE" \
    <"$SECRET_INPUT"
assert_rc 0 "first key-auth setup should succeed"
assert_not_contains "$FIRST_OUT" "$CF_SECRET" "setup output leaked a stdin secret"

CFG_DIR="$CONFIG_HOME/.config/artifact-sftp"
CONFIG="$CFG_DIR/config"
KNOWN="$CFG_DIR/known_hosts"
[ -f "$CONFIG" ] || fail "setup did not create config"
[ -f "$KNOWN" ] || fail "setup did not create known_hosts"
[ "$(file_mode "$CFG_DIR")" = 700 ] || fail "config directory mode is not 0700"
[ "$(file_mode "$CONFIG")" = 600 ] || fail "config mode is not 0600"
[ "$(file_mode "$KNOWN")" = 600 ] || fail "known_hosts mode is not 0600"
grep -Fqx "SSH_KEY=$KEY_FILE" "$CONFIG" || fail "SSH key authentication was not recorded"
grep -Fqx 'DEFAULT_TOOL=codex' "$CONFIG" || fail "default tool was not recorded"
grep -Fqx "CF_ACCESS_CLIENT_ID=$CF_ID" "$CONFIG" || fail "cf-access-id was not recorded"
grep -Fqx "CF_ACCESS_CLIENT_SECRET=$CF_SECRET" "$CONFIG" || fail "stdin secret was not written to config"
grep -Fqx 'DEFAULT_LANG=th' "$CONFIG" || fail "default lang was not recorded"
grep -Fqx 'DEFAULT_TIMEZONE=Asia/Bangkok' "$CONFIG" || fail "default timezone was not recorded"
assert_contains "$KNOWN" '[sftp.test.invalid]:2222 ssh-ed25519' "mocked host key was not pinned"

READY_OUT="$TMP_ROOT/status-ready.out"
run_capture "$READY_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 0 "status should accept the new key-auth configuration"
assert_contains "$READY_OUT" 'auth: ssh-key' "status did not report key authentication"
assert_contains "$READY_OUT" 'READY' "ready summary was not reported"
assert_not_contains "$READY_OUT" "$CF_SECRET" "status output leaked a stored secret"

# Status must classify a hand-edited URL with a path as a config issue, rather
# than claiming the host is ready and allowing the publisher to construct an
# MCP-incompatible artifact URL.
cp "$CONFIG" "$CONFIG.before-invalid-url"
sed 's#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=https://artifacts.test.invalid/prefix#' \
  "$CONFIG.before-invalid-url" >"$CONFIG"
chmod 600 "$CONFIG"
INVALID_STATUS_OUT="$TMP_ROOT/status-invalid-url.out"
run_capture "$INVALID_STATUS_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 3 "status should reject a path-bearing PUBLIC_BASE_URL"
assert_contains "$INVALID_STATUS_OUT" 'config: PUBLIC_BASE_URL must be an HTTPS origin with a host, no path/query/fragment, and no trailing slash' \
  "invalid PUBLIC_BASE_URL was not reported in the config category"
mv "$CONFIG.before-invalid-url" "$CONFIG"
chmod 600 "$CONFIG"

# READY must include semantic checks, not only key-name presence.
KEY_HOLD="$TMP_ROOT/test_key.hold"
mv "$KEY_FILE" "$KEY_HOLD"
MISSING_KEY_OUT="$TMP_ROOT/status-missing-key.out"
run_capture "$MISSING_KEY_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 3 "status should reject a missing configured SSH key"
assert_contains "$MISSING_KEY_OUT" 'ssh key: missing or unreadable' "missing SSH key was not reported"
mv "$KEY_HOLD" "$KEY_FILE"

KNOWN_HOLD="$TMP_ROOT/known-hosts.hold"
cp "$KNOWN" "$KNOWN_HOLD"
write_known_host "$KNOWN" another.test.invalid 2222
MISMATCHED_KNOWN_OUT="$TMP_ROOT/status-mismatched-known-hosts.out"
run_capture "$MISMATCHED_KNOWN_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 3 "status should reject host keys for a different endpoint"
assert_contains "$MISMATCHED_KNOWN_OUT" 'no valid key for configured host and port' \
  "mismatched known_hosts was not reported"
cp "$KNOWN_HOLD" "$KNOWN"
chmod 600 "$KNOWN"

printf '%s\n' '[sftp.test.invalid]:2222 ssh-ed25519 not-valid-key-data' >"$KNOWN"
chmod 600 "$KNOWN"
MALFORMED_KNOWN_OUT="$TMP_ROOT/status-malformed-known-hosts.out"
run_capture "$MALFORMED_KNOWN_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 3 "status should reject malformed host-key data"
assert_contains "$MALFORMED_KNOWN_OUT" 'known_hosts: malformed key data' \
  "malformed known_hosts was not reported"
cp "$KNOWN_HOLD" "$KNOWN"
chmod 600 "$KNOWN"

# The user-invocable setup skill must resolve the sibling implementation from its own
# location, not from the caller's current working directory.
WIZARD_STATUS_OUT="$TMP_ROOT/wizard-status.out"
run_from_dir_capture "$WIZARD_STATUS_OUT" "$UNRELATED_CWD" \
  env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$WIZARD_SOURCE" --status
assert_rc 0 "setup wizard --status should resolve the bundled implementation"
assert_contains "$WIZARD_STATUS_OUT" 'READY' "setup wizard did not return readiness"
assert_not_contains "$WIZARD_STATUS_OUT" "$CF_SECRET" "setup wizard status leaked a stored secret"

# Password auth must read its secret from stdin, never argv/output, and remain
# discoverable as the selected auth mode in redacted status.
PASSWORD_HOME="$TMP_ROOT/password home"
PASSWORD_SECRET='fixture-sftp-password-redact-me'  # pragma: allowlist secret
PASSWORD_STDIN="$TMP_ROOT/password.stdin"
PASSWORD_OUT="$TMP_ROOT/password-setup.out"
PASSWORD_KNOWN_SOURCE="$TMP_ROOT/password-preverified-known-hosts"
write_known_host "$PASSWORD_KNOWN_SOURCE" password.test.invalid 22
printf '%s\n' "$PASSWORD_SECRET" >"$PASSWORD_STDIN"
run_capture "$PASSWORD_OUT" env HOME="$PASSWORD_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host password.test.invalid \
  --user password-user \
  --remote-dir /files \
  --url https://password.test.invalid \
  --tool codex \
  --pass - \
  --known-hosts-file "$PASSWORD_KNOWN_SOURCE" \
  <"$PASSWORD_STDIN"
assert_rc 0 "password-auth setup should succeed with mocked paramiko"
assert_not_contains "$PASSWORD_OUT" "$PASSWORD_SECRET" "password setup output leaked its secret"
grep -Fqx "SFTP_PASS=$PASSWORD_SECRET" "$PASSWORD_HOME/.config/artifact-sftp/config" \
  || fail "stdin SFTP password was not written to config"
PASSWORD_STATUS_OUT="$TMP_ROOT/password-status.out"
run_capture "$PASSWORD_STATUS_OUT" env HOME="$PASSWORD_HOME" PATH="$TEST_PATH" \
  bash "$SETUP" --status
assert_rc 0 "password-auth status should be ready with mocked paramiko"
assert_contains "$PASSWORD_STATUS_OUT" 'auth: password' "password auth mode was not reported"
assert_not_contains "$PASSWORD_STATUS_OUT" "$PASSWORD_SECRET" "password status leaked its secret"

# Without a controlling terminal, first-run setup must stop instead of accepting secrets
# through redirected stdin or chat-driven tool arguments.
NO_TTY_HOME="$TMP_ROOT/no tty home"
mkdir -p "$NO_TTY_HOME"
NO_TTY_OUT="$TMP_ROOT/no-tty.out"
run_capture "$NO_TTY_OUT" env HOME="$NO_TTY_HOME" PATH="$TEST_PATH" \
  bash "$WIZARD_SOURCE" </dev/null
assert_rc 2 "setup wizard should require a controlling terminal"
assert_contains "$NO_TTY_OUT" 'interactive terminal is required' "no-TTY refusal was not explained"

# A second setup without --replace must fail before changing either file.
ORIGINAL_CONFIG="$TMP_ROOT/original-config"
ORIGINAL_KNOWN="$TMP_ROOT/original-known-hosts"
cp "$CONFIG" "$ORIGINAL_CONFIG"
cp "$KNOWN" "$ORIGINAL_KNOWN"
REFUSE_OUT="$TMP_ROOT/refuse-overwrite.out"
run_capture "$REFUSE_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host replacement.test.invalid \
  --user replacement-user \
  --remote-dir /replacement \
  --url https://replacement.test.invalid \
  --tool openclaw \
  --ssh-key "$KEY_FILE" \
  --known-hosts-file "$FIRST_KNOWN_SOURCE"
assert_rc 2 "setup should refuse an overwrite without --replace"
assert_contains "$REFUSE_OUT" 'configuration already exists' "overwrite refusal was not explained"
cmp -s "$CONFIG" "$ORIGINAL_CONFIG" || fail "refused setup changed config"
cmp -s "$KNOWN" "$ORIGINAL_KNOWN" || fail "refused setup changed known_hosts"

# --replace must preserve both previous files and install the replacement.
REPLACE_OUT="$TMP_ROOT/replace.out"
REPLACE_KNOWN_SOURCE="$TMP_ROOT/replacement-preverified-known-hosts"
write_known_host "$REPLACE_KNOWN_SOURCE" replacement.test.invalid 2022
run_capture "$REPLACE_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host replacement.test.invalid \
  --user replacement-user \
  --port 2022 \
  --remote-dir /replacement \
  --url https://replacement.test.invalid \
  --tool openclaw \
  --ssh-key "$KEY_FILE" \
  --known-hosts-file "$REPLACE_KNOWN_SOURCE" \
  --replace
assert_rc 0 "setup --replace should succeed"
CONFIG_BACKUP=$(find "$CFG_DIR" -maxdepth 1 -type f -name 'config.bak-*' -print -quit)
KNOWN_BACKUP=$(find "$CFG_DIR" -maxdepth 1 -type f -name 'known_hosts.bak-*' -print -quit)
[ -n "$CONFIG_BACKUP" ] || fail "--replace did not back up config"
[ -n "$KNOWN_BACKUP" ] || fail "--replace did not back up known_hosts"
[ "$(file_mode "$CONFIG_BACKUP")" = 600 ] || fail "config backup mode is not private"
[ "$(file_mode "$KNOWN_BACKUP")" = 600 ] || fail "known_hosts backup mode is not private"
cmp -s "$CONFIG_BACKUP" "$ORIGINAL_CONFIG" || fail "config backup does not match the previous file"
cmp -s "$KNOWN_BACKUP" "$ORIGINAL_KNOWN" || fail "known_hosts backup does not match the previous file"
grep -Fqx 'SFTP_HOST=replacement.test.invalid' "$CONFIG" || fail "replacement config was not installed"
assert_contains "$KNOWN" '[replacement.test.invalid]:2022 ssh-ed25519' "replacement host key was not installed"

# Status must reject permissive config modes even when the contents are valid.
chmod 644 "$CONFIG"
UNSAFE_MODE_OUT="$TMP_ROOT/status-unsafe-mode.out"
run_capture "$UNSAFE_MODE_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" --status
assert_rc 3 "status should reject an unsafe config mode"
assert_contains "$UNSAFE_MODE_OUT" 'config: unsafe mode 644' "unsafe config mode was not reported"
assert_contains "$UNSAFE_MODE_OUT" 'NOT READY' "unsafe mode did not produce a not-ready summary"

# Even when repairing an unsafe source config, backups must be newly allocated private files.
REPAIR_UNSAFE_OUT="$TMP_ROOT/repair-unsafe.out"
run_capture "$REPAIR_UNSAFE_OUT" env HOME="$CONFIG_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host replacement.test.invalid \
  --user replacement-user \
  --port 2022 \
  --remote-dir /replacement \
  --url https://replacement.test.invalid \
  --tool openclaw \
  --ssh-key "$KEY_FILE" \
  --known-hosts-file "$REPLACE_KNOWN_SOURCE" \
  --replace
assert_rc 0 "repairing an unsafe config should succeed"
for backup in "$CFG_DIR"/config.bak-* "$CFG_DIR"/known_hosts.bak-*; do
  [ "$(file_mode "$backup")" = 600 ] || fail "a replacement backup is not mode 0600"
done

# A pre-existing symlink is treated as possible tampering. The linked target and
# sibling known_hosts path must remain untouched.
SYMLINK_HOME="$TMP_ROOT/symlink home"
SYMLINK_CFG_DIR="$SYMLINK_HOME/.config/artifact-sftp"
SYMLINK_TARGET="$TMP_ROOT/symlink-target"
mkdir -p "$SYMLINK_CFG_DIR"
printf '%s\n' 'do-not-change' >"$SYMLINK_TARGET"
ln -s "$SYMLINK_TARGET" "$SYMLINK_CFG_DIR/config"
SYMLINK_OUT="$TMP_ROOT/refuse-symlink.out"
run_capture "$SYMLINK_OUT" env HOME="$SYMLINK_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host sftp.test.invalid \
  --user artifact-user \
  --remote-dir /files \
  --url https://artifacts.test.invalid \
  --tool codex \
  --ssh-key "$KEY_FILE" \
  --known-hosts-file "$FIRST_KNOWN_SOURCE" \
  --replace
assert_rc 2 "setup should refuse a config symlink"
assert_contains "$SYMLINK_OUT" 'is a symlink' "symlink refusal was not explained"
[ "$(sed -n '1p' "$SYMLINK_TARGET")" = 'do-not-change' ] || fail "symlink target was modified"
[ ! -e "$SYMLINK_CFG_DIR/known_hosts" ] || fail "symlink refusal wrote known_hosts"

# Existing directories at either target are not valid replaceable files.
DIRECTORY_HOME="$TMP_ROOT/directory target home"
DIRECTORY_CFG_DIR="$DIRECTORY_HOME/.config/artifact-sftp"
mkdir -p "$DIRECTORY_CFG_DIR/config"
DIRECTORY_OUT="$TMP_ROOT/refuse-directory.out"
run_capture "$DIRECTORY_OUT" env HOME="$DIRECTORY_HOME" PATH="$TEST_PATH" bash "$SETUP" \
  --host sftp.test.invalid \
  --user artifact-user \
  --port 2222 \
  --remote-dir /files \
  --url https://artifacts.test.invalid \
  --tool codex \
  --ssh-key "$KEY_FILE" \
  --known-hosts-file "$FIRST_KNOWN_SOURCE" \
  --replace
assert_rc 2 "setup should refuse a directory at the config target"
assert_contains "$DIRECTORY_OUT" 'not a regular file' "directory target refusal was not explained"

printf 'PASS: artifact-sftp setup offline regression tests\n'
