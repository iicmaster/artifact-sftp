#!/usr/bin/env bash
# Interactive first-run adapter for artifact-sftp. Secrets are read from a TTY and forwarded
# to the flag-driven setup implementation over stdin; they are never placed in argv.
set -euo pipefail
set +x
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
SETUP_SH="$SCRIPT_DIR/../../artifact-sftp/scripts/setup.sh"
CFG_DIR="$HOME/.config/artifact-sftp"
CONFIG="$CFG_DIR/config"
KNOWN="$CFG_DIR/known_hosts"

err() { printf '%s\n' "$*" >&2; }
die() { err "ERROR: $*"; exit 2; }
usage() {
  cat >&2 <<'EOF'
usage: setup-wizard.sh [--status | --reconfigure]

  --status       inspect local readiness without changing files or using the network
  --reconfigure  interactively replace an existing config after confirmation
EOF
}

[ -f "$SETUP_SH" ] || die "setup implementation not found: $SETUP_SH"

mode=setup
case "${1:-}" in
  '') ;;
  --status) [ "$#" -eq 1 ] || { usage; exit 2; }; exec bash "$SETUP_SH" --status ;;
  --reconfigure) [ "$#" -eq 1 ] || { usage; exit 2; }; mode=reconfigure ;;
  -h|--help) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

status_output=''
status_rc=0
if status_output=$(bash "$SETUP_SH" --status 2>&1); then
  ready=1
else
  status_rc=$?
  ready=0
fi
printf '%s\n' "$status_output"

if [ "$ready" -eq 1 ] && [ "$mode" = setup ]; then
  printf 'Already configured. No files changed.\n'
  exit 0
fi

existing=0
if [ -e "$CONFIG" ] || [ -L "$CONFIG" ] || [ -e "$KNOWN" ] || [ -L "$KNOWN" ]; then
  existing=1
fi
if [ "$existing" -eq 1 ] && [ "$mode" != reconfigure ]; then
  err "Existing configuration was not changed."
  err "Resolve the dependency or permission issue reported above."
  err "Use --reconfigure only when the stored connection settings must change."
  exit "${status_rc:-3}"
fi

if [ -t 0 ]; then
  exec 3<&0
elif exec 3<>/dev/tty 2>/dev/null; then
  :
else
  err "ERROR: an interactive terminal is required; secrets must not be collected in chat."
  if [ "$mode" = reconfigure ]; then
    err "Run this in a local terminal: bash '$0' --reconfigure"
  else
    err "Run this in a local terminal: bash '$0'"
  fi
  exit 2
fi

prompt_default() {
  local variable=$1 label=$2 default=$3 answer=''
  printf '%s [%s]: ' "$label" "$default" >&2
  IFS= read -r answer <&3 || die "terminal input ended"
  [ -n "$answer" ] || answer=$default
  printf -v "$variable" '%s' "$answer"
}

prompt_required() {
  local variable=$1 label=$2 answer=''
  while [ -z "$answer" ]; do
    printf '%s: ' "$label" >&2
    IFS= read -r answer <&3 || die "terminal input ended"
  done
  printf -v "$variable" '%s' "$answer"
}

prompt_secret() {
  local variable=$1 label=$2 answer=''
  while [ -z "$answer" ]; do
    printf '%s: ' "$label" >&2
    IFS= read -r -s answer <&3 || die "terminal input ended"
    printf '\n' >&2
  done
  printf -v "$variable" '%s' "$answer"
}

confirm() {
  local label=$1 answer=''
  printf '%s [y/N]: ' "$label" >&2
  IFS= read -r answer <&3 || die "terminal input ended"
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

config_safe() {
  case "$1" in *[!A-Za-z0-9_.:/@%+-]*) return 1 ;; *) return 0 ;; esac
}

prompt_safe_secret() {
  local variable=$1 label=$2 secret_value=''
  while :; do
    prompt_secret secret_value "$label"
    if config_safe "$secret_value"; then
      printf -v "$variable" '%s' "$secret_value"
      return 0
    fi
    secret_value=''
    err "That value contains unsupported characters. Allowed: A-Z a-z 0-9 _ . : / @ % + -"
  done
}

host='' sftp_user='' port='' remote_dir='' public_url='' default_tool=''
lang='th' timezone='Asia/Bangkok'
auth_choice='' auth_mode='' ssh_key='' op_ref=''
sftp_pass='' cf_access_id='' cf_access_secret=''
use_cf=0 host_keys=''
cleanup() {
  if [ -n "$host_keys" ]; then rm -f "$host_keys"; fi
  unset sftp_pass cf_access_secret
}
trap cleanup EXIT

err "Enter connection settings. Press Return to accept a default."
prompt_default host "SFTP host" "sftp.artifacts.ngs.bz"
prompt_default sftp_user "SFTP user" "artifacts"
prompt_default port "SFTP port" "22"
prompt_default remote_dir "Remote base directory" "/files"
prompt_default public_url "Public base URL" "https://artifacts.ngs.bz"
prompt_default lang "Default page language (html lang)" "th"
prompt_default timezone "Footer timezone" "Asia/Bangkok"

while :; do
  prompt_default default_tool "Default runtime (codex/openclaw/claude)" "codex"
  case "$default_tool" in codex|openclaw|claude) break ;; *) err "Choose codex, openclaw or claude." ;; esac
done

while :; do
  prompt_default auth_choice "Authentication (password/ssh-key/1password)" "password"
  case "$auth_choice" in
    password)
      command -v python3 >/dev/null 2>&1 && python3 -c 'import paramiko' 2>/dev/null \
        || die "password auth requires python3-paramiko; install it locally, then rerun setup"
      auth_mode=password
      prompt_safe_secret sftp_pass "SFTP password (hidden)"
      break
      ;;
    ssh-key)
      command -v sftp >/dev/null 2>&1 || die "SSH-key auth requires sftp"
      auth_mode=ssh-key
      prompt_required ssh_key "SSH private-key path"
      case "$ssh_key" in '~/'*) ssh_key="$HOME/${ssh_key#\~/}" ;; esac
      break
      ;;
    1password)
      command -v op >/dev/null 2>&1 || command -v op.exe >/dev/null 2>&1 \
        || die "1Password auth requires op or op.exe"
      command -v sftp >/dev/null 2>&1 || die "1Password auth requires sftp"
      auth_mode=1password
      err "Use vault/item IDs when names contain spaces, for example op://vault-id/item-id/private-key."
      prompt_required op_ref "1Password secret reference"
      break
      ;;
    *) err "Choose password, ssh-key, or 1password." ;;
  esac
done

if confirm "Configure a Cloudflare Zero Trust service token? (lets the publisher verify private artifacts)"; then
  use_cf=1
  prompt_required cf_access_id "Cloudflare Access client ID"
  prompt_safe_secret cf_access_secret "Cloudflare Access client secret (hidden)"
fi

case "$port" in ''|*[!0-9]*) die "SFTP port must be an integer" ;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || die "SFTP port must be between 1 and 65535"
for field in "$host" "$sftp_user" "$remote_dir" "$public_url" "$default_tool" "$lang" "$timezone" "$ssh_key" "$op_ref" "$cf_access_id"; do
  [ -z "$field" ] || config_safe "$field" \
    || die "a non-secret setting contains unsupported characters (allowed: A-Z a-z 0-9 _ . : / @ % + -)"
done

command -v ssh-keyscan >/dev/null 2>&1 || die "ssh-keyscan is required"
host_keys=$(mktemp "${TMPDIR:-/tmp}/artifact-sftp-known-hosts.XXXXXX")
if ! ssh-keyscan -p "$port" "$host" >"$host_keys" 2>/dev/null || [ ! -s "$host_keys" ]; then
  die "ssh-keyscan returned no key for $host:$port; check the host, port, and network"
fi
err "SFTP host-key fingerprints (verify these with the server owner):"
if command -v ssh-keygen >/dev/null 2>&1; then
  ssh-keygen -lf "$host_keys" -E sha256 >&2 || die "could not fingerprint the scanned host keys"
else
  err "  ssh-keygen is unavailable; the key was scanned but cannot be fingerprinted safely"
  exit 2
fi

cat >&2 <<EOF

Redacted setup summary
  SFTP:       $sftp_user@$host:$port
  Remote dir: $remote_dir
  Public URL: $public_url
  Runtime:    $default_tool
  Auth mode:  $auth_mode
  CF Access:  $(if [ "$use_cf" -eq 1 ]; then printf configured; else printf omitted; fi)
EOF

if ! confirm "Trust these host keys and write the private config?"; then
  err "Cancelled. No configuration was written."
  exit 1
fi

setup_args=(
  --host "$host"
  --user "$sftp_user"
  --port "$port"
  --remote-dir "$remote_dir"
  --url "$public_url"
  --tool "$default_tool"
  --lang "$lang"
  --timezone "$timezone"
)
case "$auth_mode" in
  password) setup_args+=(--pass -) ;;
  ssh-key) setup_args+=(--ssh-key "$ssh_key") ;;
  1password) setup_args+=(--op-ref "$op_ref") ;;
esac
if [ "$use_cf" -eq 1 ]; then
  setup_args+=(--cf-access-id "$cf_access_id" --cf-access-secret -)
fi
[ "$existing" -eq 0 ] || setup_args+=(--replace)
setup_args+=(--known-hosts-file "$host_keys")

forward_secrets() {
  [ "$auth_mode" != password ] || printf '%s\n' "$sftp_pass"
  [ "$use_cf" -eq 0 ] || printf '%s\n' "$cf_access_secret"
}

forward_secrets | bash "$SETUP_SH" "${setup_args[@]}"
unset sftp_pass cf_access_secret
bash "$SETUP_SH" --status
printf 'Setup complete. No artifact was published.\n'
