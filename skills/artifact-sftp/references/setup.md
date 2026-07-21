# artifact-sftp — one-time setup

## Server side (owner does this once; DirectAdmin shared hosting assumed)

1. Create subdomain `artifacts.ngs.bz` + DNS record.
2. Create SFTP account `artifacts` whose docroot serves the subdomain.
3. Create the directory layout under the docroot:
   ```
   openclaw/private/   openclaw/public/
   codex/private/      codex/public/
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

## Install the plugin (Codex / OpenClaw)

The skill ships inside a plugin at `plugins/artifact-sftp/`; the marketplace manifest is
`.agents/plugins/marketplace.json` at the repo root. Register the repo as a **local**
marketplace, then install — from a checkout of this repo:

```bash
codex plugin marketplace add "$PWD"                 # discovers .agents/plugins/marketplace.json
codex plugin add artifact-sftp@ngs-agent-skills     # installs into ~/.codex
# start a FRESH codex process so the new skill is indexed
```

OpenClaw consumes the same marketplace format under `~/.openclaw/plugins`; use its plugin
CLI/UX to add the same local source. Git source works too once pushed:
`codex plugin marketplace add ngs-th/agent-skills` (owner/repo form).

## Client side (each machine): one-time config

`scripts/setup.sh` pins the host key and writes `~/.config/artifact-sftp/config` (0600). It is
flag-driven; the password is read from **stdin**, never argv:

```bash
# password account (current deployment) — needs python3-paramiko.
# secrets go through stdin (never argv/ps/history), one per line: SFTP pass, then basic-auth:
printf '%s\n%s\n' "$SFTP_PASSWORD" "artifacts-private:$VIEWER_PASS" | bash scripts/setup.sh \
  --host sftp.artifacts.ngs.bz --user artifacts --port 22 \
  --remote-dir /files --url https://artifacts.ngs.bz --tool codex \
  --pass - --basic-auth -

# OR a local SSH key (no paramiko needed):
bash scripts/setup.sh --host sftp.artifacts.ngs.bz --user artifacts \
  --remote-dir /files --url https://artifacts.ngs.bz --tool codex \
  --ssh-key ~/.ssh/id_ed25519_artifacts

# OR a key from 1Password (op / op.exe via WSL; desktop app unlocked):
bash scripts/setup.sh --host sftp.artifacts.ngs.bz --user artifacts \
  --remote-dir /files --url https://artifacts.ngs.bz --tool codex \
  --op-ref 'op://Internal Shared/artifacts.ngs.bz - sftp/private key'
```

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
printf '%s' "$CF_ACCESS_CLIENT_SECRET" | bash scripts/setup.sh \
  --host sftp.artifacts.ngs.bz --user artifacts --remote-dir /files \
  --url https://artifacts.ngs.bz --tool codex --ssh-key ~/.ssh/id_ed25519_artifacts \
  --cf-access-id "$CF_ACCESS_CLIENT_ID" --cf-access-secret -
```

`publish.sh` then sends `CF-Access-Client-Id`/`CF-Access-Client-Secret` headers on the verify
fetch and confirms the served sha256 matches. Without the token, private publishes work but
skip the HTTP verify (upload is still confirmed via SFTP).

Notes for the current deployment: web is proxied by Cloudflare (`artifacts.ngs.bz`), SFTP
DNS points straight at the origin (`sftp.artifacts.ngs.bz`). SFTP login lands in a chroot
`/`; artifacts live under `/files/{openclaw,codex}/{private,public}`.

## Smoke test

```bash
printf '<title>smoke</title><p>hello</p>' > /tmp/smoke.html
bash scripts/publish.sh --slug smoke-test --tool codex /tmp/smoke.html   # private
bash scripts/publish.sh --delete smoke-test --tool codex                 # clean up
```
