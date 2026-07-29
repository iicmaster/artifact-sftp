# artifact-sftp — one-time setup

## Server side (owner does this once; DirectAdmin shared hosting assumed)

1. Create subdomain `artifacts.ngs.bz` + DNS record.
2. Create SFTP account `artifacts` whose docroot serves the subdomain.
3. Create the directory layout under the docroot:
   ```
   openclaw/private/   openclaw/public/
   codex/private/      codex/public/
   claude/private/     claude/public/
   ```
4. Protect both `*/private/` dirs with HTTP basic auth (`.htaccess` + `.htpasswd`
   outside the docroot). Example `.htaccess`:
   ```apache
   AuthType Basic
   AuthName "private artifacts"
   AuthUserFile /home/artifacts/.htpasswd
   Require valid-user
   ```
5. Auth: install an SSH public key for the account when possible. If the hosting only
   allows password auth (current deployment does — chroot forbids `~/.ssh`), the script
   falls back to the paramiko helper via `SFTP_PASS` in the client config; that requires
   `python3-paramiko` on the client. Keep credentials in 1Password.
6. Recommended: serve this subdomain static-only, no app cookies/sessions on it —
   uploaded HTML runs on this origin (stored-XSS blast radius).
7. Add a 1Password item (e.g. `artifacts.ngs.bz - sftp`) holding the SSH private key.

## Install the plugin

Install the standalone public marketplace in Codex:

```bash
codex plugin marketplace add iicmaster/artifact-sftp
codex plugin add artifact-sftp@iicmaster-artifact-sftp
# Start a FRESH Codex process so the installed version and both skills are indexed.
```

For local development, replace `iicmaster/artifact-sftp` with the path to this checkout.
In the fresh Codex session, start first-run setup with:

```text
$artifact-sftp:artifact-sftp-setup
```

OpenClaw can install a local checkout directly, then expose the bundled setup skill:

```bash
git clone https://github.com/iicmaster/artifact-sftp.git
openclaw plugins install ./artifact-sftp
```

Invoke it with `/skill artifact-sftp-setup`. OpenClaw does not consume the Codex
`.agents/plugins/marketplace.json`.

## Client side (each machine): one-time config

The setup command launches an interactive terminal wizard, shows the SFTP host-key
fingerprints for confirmation, and writes `~/.config/artifact-sftp/config` plus
`known_hosts` at mode `0600`. It never publishes a smoke artifact. It also supports a
read-only readiness check:

Required client tools are `ssh-keyscan`, `ssh-keygen`, `curl`, and either `sha256sum` or
`shasum`. SSH-key and 1Password modes also need `sftp`; password mode needs Python 3 with
`paramiko`. The command reports missing dependencies before writing configuration.

```bash
PLUGIN_DIR=/path/to/artifact-sftp
bash "$PLUGIN_DIR/skills/artifact-sftp-setup/scripts/setup-wizard.sh" --status
```

For automation, the implementation remains flag-driven. Secrets are read from **stdin**,
never argv. `PLUGIN_DIR` must point at the installed or initialized `artifact-sftp` plugin
directory. Automation must also supply a host-key file whose fingerprints were verified
with the server owner through an independent channel; `setup.sh` refuses unconfirmed TOFU:

```bash
KNOWN_HOSTS_FILE=/secure/path/artifact-sftp.known_hosts
ssh-keyscan -p 22 sftp.artifacts.ngs.bz >"$KNOWN_HOSTS_FILE"
ssh-keygen -lf "$KNOWN_HOSTS_FILE" -E sha256
# Compare every fingerprint with the server owner before continuing.
chmod 600 "$KNOWN_HOSTS_FILE"
```

Then configure one authentication mode:

```bash
# password account (current deployment) — needs python3-paramiko.
# secrets go through stdin (never argv/ps/history), one per line: SFTP pass, then basic-auth:
printf '%s\n%s\n' "$SFTP_PASSWORD" "artifacts-private:$VIEWER_PASS" | \
  bash "$PLUGIN_DIR/skills/artifact-sftp/scripts/setup.sh" \
    --host sftp.artifacts.ngs.bz --user artifacts --port 22 \
    --remote-dir /files --url https://artifacts.ngs.bz --tool codex \
    --pass - --basic-auth - --known-hosts-file "$KNOWN_HOSTS_FILE"

# OR a local SSH key (no paramiko needed):
bash "$PLUGIN_DIR/skills/artifact-sftp/scripts/setup.sh" \
  --host sftp.artifacts.ngs.bz --user artifacts \
  --remote-dir /files --url https://artifacts.ngs.bz --tool codex \
  --ssh-key ~/.ssh/id_ed25519_artifacts --known-hosts-file "$KNOWN_HOSTS_FILE"

# OR a key from 1Password (op / op.exe via WSL; desktop app unlocked):
bash "$PLUGIN_DIR/skills/artifact-sftp/scripts/setup.sh" \
  --host sftp.artifacts.ngs.bz --user artifacts \
  --remote-dir /files --url https://artifacts.ngs.bz --tool codex \
  --op-ref 'op://vault-id/item-id/private-key' --known-hosts-file "$KNOWN_HOSTS_FILE"
```

The script refuses to overwrite either file by default. An explicitly approved repair uses
`--replace`; it first backs up both the config and pinned host keys. Replacement rewrites the
entire config, so repeat every setting that must be retained, including `BASIC_AUTH`, the
chosen SFTP auth mode, and any Cloudflare Access token.

Config values must be shell-safe (the file is both `source`d by `publish.sh` and split by
`sftp_helper.py`); `setup.sh` rejects a password with spaces/quotes/`$` and points you to
`--ssh-key`. To hand-write the config instead, the keys are: `SFTP_HOST`, `SFTP_USER`,
`SFTP_PORT`, `REMOTE_DIR`, `PUBLIC_BASE_URL`, `DEFAULT_TOOL`, one of
`SFTP_PASS`/`SSH_KEY`/`OP_KEY_REF`, and optional `BASIC_AUTH`,
`CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` — one `KEY=value` per line, `chmod 600`.

## Private verify behind Cloudflare Access

The current deployment gates `*/private/` with **Cloudflare Access (Zero Trust SSO)**, not
`.htpasswd` — so `BASIC_AUTH` cannot satisfy it. A private publish still uploads fine and
`publish.sh` exits 0, but it prints `HTTP verify skipped (Cloudflare Access)` because it
cannot fetch the artifact back to hash-check it. `/public/` is open and verifies normally.

To make private artifacts hash-verify, add a **Cloudflare Access service token** (Zero Trust →
Access → Service Auth → create a service token; then add its identity to the Access policy for
`artifacts.ngs.bz`). Store it in the config:

```bash
printf '%s' "$CF_ACCESS_CLIENT_SECRET" | \
  bash "$PLUGIN_DIR/skills/artifact-sftp/scripts/setup.sh" \
  --host sftp.artifacts.ngs.bz --user artifacts --remote-dir /files \
  --url https://artifacts.ngs.bz --tool codex --ssh-key ~/.ssh/id_ed25519_artifacts \
  --cf-access-id "$CF_ACCESS_CLIENT_ID" --cf-access-secret - \
  --known-hosts-file "$KNOWN_HOSTS_FILE" --replace
```

`publish.sh` then sends `CF-Access-Client-Id`/`CF-Access-Client-Secret` headers on the verify
fetch and confirms the served sha256 matches. Without the token, private publishes work but
skip the HTTP verify (upload is still confirmed via SFTP).

Notes for the current deployment: web is proxied by Cloudflare (`artifacts.ngs.bz`), SFTP
DNS points straight at the origin (`sftp.artifacts.ngs.bz`). SFTP login lands in a chroot
`/`; artifacts live under `/files/{openclaw,codex,claude}/{private,public}`.

## Smoke test

```bash
printf '<title>smoke</title><p>hello</p>' > /tmp/smoke.html
bash "$PLUGIN_DIR/skills/artifact-sftp/scripts/publish.sh" \
  --slug smoke-test --tool codex /tmp/smoke.html                         # private
bash "$PLUGIN_DIR/skills/artifact-sftp/scripts/publish.sh" \
  --delete smoke-test --tool codex                                      # clean up
```

Run the smoke test only as a separate, explicit publish action after setup succeeds.
