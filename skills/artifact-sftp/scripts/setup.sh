#!/usr/bin/env bash
# artifact-sftp setup — pin the SFTP host key and write ~/.config/artifact-sftp/config (0600).
# Flag-driven so an agent can run it non-interactively. The password (if any) is read from
# STDIN, never argv, so it never lands in a process listing or shell history.
#
# usage:
#   setup.sh --status
#   setup.sh --host H --user U [--port 22] --remote-dir /files --url https://host [--tool codex]
#            [--cf-access-id ID --cf-access-secret -] [--lang th] [--timezone Asia/Bangkok]
#            --known-hosts-file FILE [--replace]
#            ( --pass - | --ssh-key PATH | --op-ref op://... )
#   Secrets are read from stdin, ONE PER LINE, in this fixed order (only the ones you
#   requested with -): SFTP password, cf-access-secret. Example:
#   Cloudflare Zero Trust service token verifies private artifacts:
#   printf '%s' "$CF_SECRET" | setup.sh ... --ssh-key K --cf-access-id "$CF_ID" --cf-access-secret -
set -euo pipefail
set +x
umask 077

if [ "${ARTIFACT_SFTP_MCP_CALL:-}" != '1' ]; then
  printf '%s\n' 'ERROR: setup.sh is internal to Artifact SFTP MCP; AI agents must use artifact_sftp.setup_status.' >&2
  exit 10
fi

CFG_DIR="$HOME/.config/artifact-sftp"
CONFIG="$CFG_DIR/config"
KNOWN="$CFG_DIR/known_hosts"

err() { printf '%s\n' "$*" >&2; }
die() { err "ERROR: $*"; exit 2; }
_stat_perm() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
_config_count() { awk -F= -v key="$1" '$1 == key { count++ } END { print count + 0 }' "$CONFIG"; }
_config_value() { sed -n "s/^$1=//p" "$CONFIG" | tail -n 1; }
_shell_safe() { case "$1" in *[!A-Za-z0-9_.:/@%+-]*) return 1;; *) return 0;; esac; }
# PUBLIC_BASE_URL is appended with /<tool>/<visibility>/<slug>/ by publish.sh.
# Keep it an HTTPS origin with an authority, no path/query/fragment, and no
# trailing slash. The MCP result contract maps the origin directly to
# /<tool>/<visibility>/<slug>/, so accepting a path here could publish bytes
# successfully but make the returned URL fail that contract.
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
_config_shape_valid() {
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) return 1 ;; esac
    key=${line%%=*}
    value=${line#*=}
    case "$key" in
      SFTP_HOST|SFTP_USER|SFTP_PORT|REMOTE_DIR|PUBLIC_BASE_URL|DEFAULT_TOOL|SFTP_PASS|SSH_KEY|OP_KEY_REF|CF_ACCESS_CLIENT_ID|CF_ACCESS_CLIENT_SECRET|DEFAULT_LANG|DEFAULT_TIMEZONE) ;;
      *) return 1 ;;
    esac
    [ -n "$value" ] && _shell_safe "$value" || return 1
  done < "$CONFIG"
}
_config_keys_unique() {
  awk -F= '!/^#/ && NF >= 2 { if (++seen[$1] > 1) exit 1 }' "$CONFIG"
}
_known_hosts_has_target() {
  local file=$1 host=$2 port=$3 expected=$2
  [ "$port" = 22 ] || expected="[$host]:$port"
  awk -v expected="$expected" \
    '$1 == expected && $2 ~ /^(ssh-|ecdsa-|sk-)/ && length($3) > 0 { found=1 }
     END { exit(found ? 0 : 1) }' "$file"
}

status() {
  local issues=0 perm auth_count=0 auth='none' tool='' count config_ok=1 shape_ok=1
  local host='' port='' ssh_key=''
  printf 'artifact-sftp setup status\n'

  if [ -L "$CFG_DIR" ]; then
    printf 'config directory: unsafe symlink\n'
    printf 'NOT READY (1 issue(s))\n'
    return 3
  elif [ -e "$CFG_DIR" ] && [ ! -d "$CFG_DIR" ]; then
    printf 'config directory: not a directory\n'
    printf 'NOT READY (1 issue(s))\n'
    return 3
  elif [ -d "$CFG_DIR" ]; then
    perm=$(_stat_perm "$CFG_DIR")
    case "$perm" in
      700) printf 'config directory: present (mode 700)\n' ;;
      *) printf 'config directory: unsafe mode %s (need 700)\n' "$perm"; issues=$((issues + 1)) ;;
    esac
  fi

  if [ -L "$CONFIG" ]; then
    printf 'config: unsafe symlink\n'; issues=$((issues + 1))
    config_ok=0
  elif [ -e "$CONFIG" ] && [ ! -f "$CONFIG" ]; then
    printf 'config: not a regular file\n'; issues=$((issues + 1))
    config_ok=0
  elif [ ! -f "$CONFIG" ]; then
    printf 'config: missing\n'; issues=$((issues + 1))
    config_ok=0
  else
    perm=$(_stat_perm "$CONFIG")
    case "$perm" in
      600|400) printf 'config: present (mode %s)\n' "$perm" ;;
      *) printf 'config: unsafe mode %s (need 600 or 400)\n' "$perm"; issues=$((issues + 1)) ;;
    esac
    if ! _config_shape_valid; then
      printf 'config: invalid or unsafe line\n'; issues=$((issues + 1)); config_ok=0; shape_ok=0
    fi
    if ! _config_keys_unique; then
      printf 'config: duplicate keys\n'; issues=$((issues + 1)); config_ok=0
    fi
    for key in SFTP_HOST SFTP_USER SFTP_PORT REMOTE_DIR PUBLIC_BASE_URL DEFAULT_TOOL; do
      count=$(_config_count "$key")
      if [ "$count" -ne 1 ] || [ -z "$(_config_value "$key")" ]; then
        printf 'config key: %s missing or duplicated\n' "$key"; issues=$((issues + 1)); config_ok=0
      fi
    done
    if [ "$shape_ok" -eq 1 ] && [ "$(_config_count PUBLIC_BASE_URL)" -eq 1 ] \
       && [ -n "$(_config_value PUBLIC_BASE_URL)" ] \
       && ! _public_base_url_valid "$(_config_value PUBLIC_BASE_URL)"; then
      printf 'config: PUBLIC_BASE_URL must be an HTTPS origin with a host, no path/query/fragment, and no trailing slash\n'
      issues=$((issues + 1)); config_ok=0
    fi

    if [ "$(_config_count SFTP_PASS)" -eq 1 ]; then auth='password'; auth_count=$((auth_count + 1)); fi
    if [ "$(_config_count SSH_KEY)" -eq 1 ]; then auth='ssh-key'; auth_count=$((auth_count + 1)); fi
    if [ "$(_config_count OP_KEY_REF)" -eq 1 ]; then auth='1password'; auth_count=$((auth_count + 1)); fi
    if [ "$auth_count" -ne 1 ]; then
      printf 'auth: invalid (%s methods configured)\n' "$auth_count"; issues=$((issues + 1))
    else
      printf 'auth: %s\n' "$auth"
    fi

    tool=$(_config_value DEFAULT_TOOL)
    case "$tool" in
      codex|openclaw|claude) printf 'default tool: %s\n' "$tool" ;;
      *) printf 'default tool: invalid\n'; issues=$((issues + 1)) ;;
    esac

    case "$auth" in
      password)
        if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import paramiko' 2>/dev/null; then
          printf 'dependency: python3-paramiko missing\n'; issues=$((issues + 1))
        fi
        ;;
      ssh-key)
        ssh_key=$(_config_value SSH_KEY)
        if [ ! -f "$ssh_key" ] || [ ! -r "$ssh_key" ]; then
          printf 'ssh key: missing or unreadable\n'; issues=$((issues + 1))
        fi
        if ! command -v sftp >/dev/null 2>&1; then
          printf 'dependency: sftp missing\n'; issues=$((issues + 1))
        fi
        ;;
      1password)
        if ! command -v op >/dev/null 2>&1 && ! command -v op.exe >/dev/null 2>&1; then
          printf 'dependency: op/op.exe missing\n'; issues=$((issues + 1))
        fi
        if ! command -v sftp >/dev/null 2>&1; then
          printf 'dependency: sftp missing\n'; issues=$((issues + 1))
        fi
        ;;
    esac
  fi

  if [ -L "$KNOWN" ]; then
    printf 'known_hosts: unsafe symlink\n'; issues=$((issues + 1))
  elif [ -e "$KNOWN" ] && [ ! -f "$KNOWN" ]; then
    printf 'known_hosts: not a regular file\n'; issues=$((issues + 1))
  elif [ ! -s "$KNOWN" ]; then
    printf 'known_hosts: missing or empty\n'; issues=$((issues + 1))
  else
    perm=$(_stat_perm "$KNOWN")
    case "$perm" in
      600|400) printf 'known_hosts: present (mode %s)\n' "$perm" ;;
      *) printf 'known_hosts: unsafe mode %s (need 600 or 400)\n' "$perm"; issues=$((issues + 1)) ;;
    esac
    if ! command -v ssh-keygen >/dev/null 2>&1; then
      printf 'dependency: ssh-keygen missing\n'; issues=$((issues + 1))
    elif ! ssh-keygen -lf "$KNOWN" -E sha256 >/dev/null 2>&1; then
      printf 'known_hosts: malformed key data\n'; issues=$((issues + 1))
    fi
    if [ "$config_ok" -eq 1 ]; then
      host=$(_config_value SFTP_HOST)
      port=$(_config_value SFTP_PORT)
      case "$port" in ''|*[!0-9]*) port=invalid ;; esac
      if [ "$port" = invalid ] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        printf 'config port: invalid\n'; issues=$((issues + 1))
      elif ! _known_hosts_has_target "$KNOWN" "$host" "$port"; then
        printf 'known_hosts: no valid key for configured host and port\n'; issues=$((issues + 1))
      fi
    fi
  fi

  if ! command -v curl >/dev/null 2>&1; then
    printf 'dependency: curl missing\n'; issues=$((issues + 1))
  fi
  if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
    printf 'dependency: sha256sum/shasum missing\n'; issues=$((issues + 1))
  fi

  if [ "$issues" -eq 0 ]; then
    printf 'READY\n'
    return 0
  fi
  printf 'NOT READY (%s issue(s))\n' "$issues"
  return 3
}

if [ "${1:-}" = --status ]; then
  [ "$#" -eq 1 ] || die "--status takes no other arguments"
  status
  exit $?
fi

HOST='' SUSER='' PORT=22 REMOTE='' URL='' TOOL=codex AUTH_MODE='' SSH_KEY='' OP_REF='' READ_PASS=0 REPLACE=0 AUTH_CHOICES=0 LANG_VAL='' TZ_VAL=''
KNOWN_SOURCE=''
CF_ID='' CF_SECRET='' READ_CFSEC=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host)        [ $# -ge 2 ] || die "--host needs a value"; HOST=$2; shift 2 ;;
    --user)        [ $# -ge 2 ] || die "--user needs a value"; SUSER=$2; shift 2 ;;
    --port)        [ $# -ge 2 ] || die "--port needs a value"; PORT=$2; shift 2 ;;
    --remote-dir)  [ $# -ge 2 ] || die "--remote-dir needs a value"; REMOTE=$2; shift 2 ;;
    --url)         [ $# -ge 2 ] || die "--url needs a value"; URL=$2; shift 2 ;;
    --tool)        [ $# -ge 2 ] || die "--tool needs a value"; TOOL=$2; shift 2 ;;
    --pass)        [ "${2:-}" = - ] || die "--pass only accepts '-' (password is read from stdin)"; AUTH_MODE=pass; READ_PASS=1; AUTH_CHOICES=$((AUTH_CHOICES + 1)); shift 2 ;;
    --ssh-key)     [ $# -ge 2 ] || die "--ssh-key needs a value"; AUTH_MODE=key; SSH_KEY=$2; AUTH_CHOICES=$((AUTH_CHOICES + 1)); shift 2 ;;
    --op-ref)      [ $# -ge 2 ] || die "--op-ref needs a value"; AUTH_MODE=op; OP_REF=$2; AUTH_CHOICES=$((AUTH_CHOICES + 1)); shift 2 ;;
    --cf-access-id)     [ $# -ge 2 ] || die "--cf-access-id needs a value"; CF_ID=$2; shift 2 ;;
    --cf-access-secret) [ "${2:-}" = - ] || die "--cf-access-secret only accepts '-' (read from stdin)"; READ_CFSEC=1; shift 2 ;;
    --lang)        [ $# -ge 2 ] || die "--lang needs a value"; LANG_VAL=$2; shift 2 ;;
    --timezone)    [ $# -ge 2 ] || die "--timezone needs a value"; TZ_VAL=$2; shift 2 ;;
    --known-hosts-file) [ $# -ge 2 ] || die "--known-hosts-file needs a value"; KNOWN_SOURCE=$2; shift 2 ;;
    --replace)      REPLACE=1; shift ;;
    -h|--help)     sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 0 ;;
    *)             die "unknown arg: $1" ;;
  esac
done

[ -n "$HOST" ] && [ -n "$SUSER" ] && [ -n "$REMOTE" ] && [ -n "$URL" ] \
  || die "required: --host --user --remote-dir --url"
[ -n "$URL" ] && _public_base_url_valid "$URL" \
  || die "--url must be an HTTPS origin with a host, no path/query/fragment, and no trailing slash"
[ "$AUTH_CHOICES" -eq 1 ] || die "pick exactly one auth mode: --pass - | --ssh-key PATH | --op-ref op://..."
case "$TOOL" in openclaw|codex|claude) ;; *) die "--tool must be openclaw, codex or claude (got '$TOOL')";; esac
case "$PORT" in ''|*[!0-9]*) die "--port must be an integer";; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "--port must be between 1 and 65535"
# Cloudflare Access service token (optional) — needs BOTH parts or neither.
if [ -n "$CF_ID" ] || [ "$READ_CFSEC" = 1 ]; then
  { [ -n "$CF_ID" ] && [ "$READ_CFSEC" = 1 ]; } || die "Cloudflare Access needs BOTH --cf-access-id and --cf-access-secret -"
fi

# Config is BOTH sourced by bash (publish.sh) AND split on first '=' (sftp_helper.py), so every
# value must be raw and shell-safe. Reject values that would break `. config` — no quoting can
# satisfy both readers. Keys/urls are unlikely to contain these; a password might.
# Allowlist (robust): only chars that are safe both as an unquoted `KEY=value` bash source
# AND as a raw split value in sftp_helper.py. Anything else is rejected. '-' is last = literal.
for v in "$HOST" "$SUSER" "$PORT" "$REMOTE" "$URL" "$TOOL" "$SSH_KEY" "$OP_REF" "$CF_ID" "$LANG_VAL" "$TZ_VAL"; do
  [ -z "$v" ] || _shell_safe "$v" || die "value contains characters that break config sourcing: '$v'"
done

[ -L "$CFG_DIR" ] && die "refusing: $CFG_DIR is a symlink (possible tamper)"
[ -e "$CFG_DIR" ] && [ ! -d "$CFG_DIR" ] && die "refusing: $CFG_DIR is not a directory"
[ -L "$CONFIG" ] && die "refusing: $CONFIG is a symlink (possible tamper)"
[ -L "$KNOWN" ] && die "refusing: $KNOWN is a symlink (possible tamper)"
[ -e "$CONFIG" ] && [ ! -f "$CONFIG" ] && die "refusing: $CONFIG is not a regular file"
[ -e "$KNOWN" ] && [ ! -f "$KNOWN" ] && die "refusing: $KNOWN is not a regular file"
if { [ -e "$CONFIG" ] || [ -e "$KNOWN" ]; } && [ "$REPLACE" -ne 1 ]; then
  die "configuration already exists; inspect with --status, then rerun with --replace to back it up and replace it"
fi
[ -n "$KNOWN_SOURCE" ] || die "--known-hosts-file is required; use the interactive setup command to scan and confirm fingerprints"
[ ! -L "$KNOWN_SOURCE" ] || die "refusing: --known-hosts-file is a symlink"
[ -f "$KNOWN_SOURCE" ] && [ -s "$KNOWN_SOURCE" ] && [ -r "$KNOWN_SOURCE" ] \
  || die "--known-hosts-file must be a readable, non-empty regular file"
command -v ssh-keygen >/dev/null 2>&1 || die "ssh-keygen is required"
ssh-keygen -lf "$KNOWN_SOURCE" -E sha256 >/dev/null 2>&1 \
  || die "--known-hosts-file contains malformed host-key data"
_known_hosts_has_target "$KNOWN_SOURCE" "$HOST" "$PORT" \
  || die "--known-hosts-file has no valid key for $HOST:$PORT"
case "$AUTH_MODE" in
  pass)
    command -v python3 >/dev/null 2>&1 && python3 -c 'import paramiko' 2>/dev/null \
      || die "password auth requires python3-paramiko"
    ;;
  key)
    [ -f "$SSH_KEY" ] && [ -r "$SSH_KEY" ] || die "SSH key is not a readable file: $SSH_KEY"
    command -v sftp >/dev/null 2>&1 || die "SSH-key auth requires sftp"
    ;;
  op)
    command -v op >/dev/null 2>&1 || command -v op.exe >/dev/null 2>&1 \
      || die "1Password auth requires op or op.exe"
    command -v sftp >/dev/null 2>&1 || die "1Password auth requires sftp"
    ;;
esac
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 \
  || die "sha256sum or shasum is required"

# Secrets come from stdin, never argv (argv leaks via ps/history). Fixed line order for the
# ones requested with -: SFTP password, cf-access-secret. Validated before any side effect
# so a bad secret fails fast.
PASS=''
if [ "$READ_PASS" = 1 ]; then
  IFS= read -r PASS || true
  [ -n "$PASS" ] || die "--pass - was given but stdin was empty"
  _shell_safe "$PASS" || die "password contains characters this config format cannot store (space, quote, \$, backtick, backslash, or leading #) — use --ssh-key instead"
fi
if [ "$READ_CFSEC" = 1 ]; then
  IFS= read -r CF_SECRET || true
  [ -n "$CF_SECRET" ] || die "--cf-access-secret - was given but stdin had no (further) line"
  _shell_safe "$CF_SECRET" || die "cf-access-secret has characters this config format cannot store"
fi

mkdir -p "$CFG_DIR"
chmod 700 "$CFG_DIR"
tmpkh=''
tmpcfg=''
cleanup() {
  [ -z "$tmpkh" ] || rm -f "$tmpkh"
  [ -z "$tmpcfg" ] || rm -f "$tmpcfg"
}
trap cleanup EXIT

# Stage both files at mode 0600 before replacing either destination.
tmpkh=$(mktemp "$CFG_DIR/known_hosts.XXXXXX")
cp "$KNOWN_SOURCE" "$tmpkh"
chmod 600 "$tmpkh"

tmpcfg=$(mktemp "$CFG_DIR/config.XXXXXX")
{
  printf 'SFTP_HOST=%s\n' "$HOST"
  printf 'SFTP_USER=%s\n' "$SUSER"
  printf 'SFTP_PORT=%s\n' "$PORT"
  printf 'REMOTE_DIR=%s\n' "$REMOTE"
  printf 'PUBLIC_BASE_URL=%s\n' "$URL"
  [ -n "$TOOL" ]  && printf 'DEFAULT_TOOL=%s\n' "$TOOL"
  [ -n "$LANG_VAL" ] && printf 'DEFAULT_LANG=%s\n' "$LANG_VAL"
  [ -n "$TZ_VAL" ] && printf 'DEFAULT_TIMEZONE=%s\n' "$TZ_VAL"
  [ -n "$CF_ID" ] && printf 'CF_ACCESS_CLIENT_ID=%s\n' "$CF_ID"
  [ -n "$CF_SECRET" ] && printf 'CF_ACCESS_CLIENT_SECRET=%s\n' "$CF_SECRET"
  case "$AUTH_MODE" in
    pass) printf 'SFTP_PASS=%s\n' "$PASS" ;;
    key)  printf 'SSH_KEY=%s\n'   "$SSH_KEY" ;;
    op)   printf 'OP_KEY_REF=%s\n' "$OP_REF" ;;
  esac
} > "$tmpcfg"
chmod 600 "$tmpcfg"

if [ "$REPLACE" -eq 1 ]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup_one() {
    local source=$1 label=$2 destination
    destination=$(mktemp "$source.bak-$stamp.XXXXXX")
    if ! cp "$source" "$destination"; then
      rm -f "$destination"
      die "could not back up $label"
    fi
    chmod 600 "$destination"
    err "backed up previous $label -> $destination"
  }
  [ ! -f "$CONFIG" ] || backup_one "$CONFIG" config
  [ ! -f "$KNOWN" ] || backup_one "$KNOWN" known_hosts
fi
mv -f "$tmpkh" "$KNOWN"; tmpkh=''
mv -f "$tmpcfg" "$CONFIG"; tmpcfg=''
err "pinned host key -> $KNOWN"
err "wrote config -> $CONFIG (mode 600)"
err "setup complete; no artifact was published"
