# Artifact SFTP

Artifact SFTP is a Codex and OpenClaw plugin for publishing one self-contained HTML
artifact to your own SFTP-backed web host. It returns a stable URL, keeps versioned
snapshots, and defaults to private visibility.

The repository contains no hosting credentials and does not grant access to the
maintainer's deployment. You need an SFTP account and a web server that serves its
upload directory.

## What it does

- Publishes a single self-contained HTML file to a stable URL.
- Keeps immutable timestamped versions beside the current `index.html`.
- Separates runtimes (`codex`, `openclaw`, `claude`), and `private` and `public`, in the URL path.
- Pins and verifies the SFTP host key.
- Supports SSH keys, 1Password SSH-key references, or password authentication through
  Paramiko.
- Blocks common secret patterns before upload and verifies public content by SHA-256.
- Provides an interactive first-run setup skill without placing secrets in
  chat or process arguments.

## Install

### Codex

```bash
codex plugin marketplace add iicmaster/artifact-sftp
codex plugin add artifact-sftp@iicmaster-artifact-sftp
```

Start a fresh Codex process after installation, then run:

```text
$artifact-sftp:artifact-sftp-setup
```

### OpenClaw

```bash
git clone https://github.com/iicmaster/artifact-sftp.git
openclaw plugins install ./artifact-sftp
```

Then run:

```text
/skill artifact-sftp-setup
```

The setup wizard scans the SFTP host key, displays every fingerprint for independent
verification, and writes:

- `~/.config/artifact-sftp/config` with mode `0600`
- `~/.config/artifact-sftp/known_hosts` with mode `0600`

It does not publish a smoke artifact. Password authentication requires Python
3 with [`paramiko`](https://www.paramiko.org/) importable by `python3`; SSH-key
and 1Password modes require the OpenSSH `sftp` client.

## Publish

Ask the runtime to publish a self-contained HTML artifact, or invoke the
bundled script:

```bash
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh \
  --slug my-report --tool codex report.html

bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh \
  --slug my-report --tool codex --public report.html
```

The default is private. A public publish is readable by anyone who has the
URL. The last line of successful stdout is always the artifact URL.

Useful operations:

```bash
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh --list --tool codex
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh \
  --slug my-report --tool codex --public --dry-run report.html
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh \
  --delete my-report --tool codex
```

See [the setup guide](skills/artifact-sftp/references/setup.md) for server layout,
automation, authentication modes, and Cloudflare Access verification.

## Security model

- Treat publishing as data exfiltration: inspect every artifact before upload.
- Never put credentials, tokens, private keys, customer data, or unapproved
  file contents in an artifact.
- Never disable strict host-key checking to work around a mismatch.
- The local config is rejected if it is a symlink, not a regular file, or
  readable by other users.
- HTML executes on the artifact origin. Use a dedicated static-only origin
  with no application cookies or sessions.
- `--allow-sensitive` is an explicit override, not a safety guarantee.

For vulnerability reports, follow [SECURITY.md](SECURITY.md).

## Development

The test suites are offline: they replace SFTP and HTTP clients with throwaway
mocks and never read the real local configuration.

```bash
bash skills/artifact-sftp/scripts/test_publish.sh
bash skills/artifact-sftp/scripts/test_setup.sh

for script in skills/artifact-sftp/scripts/*.sh \
  skills/artifact-sftp-setup/scripts/*.sh; do
  bash -n "$script"
done
python3 -m py_compile skills/artifact-sftp/scripts/sftp_helper.py
```

## License

[MIT](LICENSE)
