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
- Keeps the stamped current file and snapshot in `docs/artifacts/<tool>/<visibility>/<slug>/`
  before any SFTP upload.
- Includes a dedicated skill that reads a just-published artifact from that local copy (its
  private viewer URL cannot be fetched over HTTP).
- Separates runtimes (`codex`, `openclaw`, `claude`), and `private` and `public`, in the URL path.
- Pins and verifies the SFTP host key.
- Supports SSH keys, 1Password SSH-key references, or password authentication through
  Paramiko.
- Blocks common secret patterns before upload and verifies public content by SHA-256.
- Provides an interactive first-run setup skill without placing secrets in
  chat or process arguments.

## Agent Plugins compatibility

The portable package root is [plugin.json](plugin.json), which targets the Agent Plugins
1.0.0 schema and exposes its immediate `skills/` children as Agent Skills. The existing
`.codex-plugin/` and `.claude-plugin/` files are compatibility metadata for their current
installers; the root manifest is the portable source of plugin identity and metadata.

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

### Claude Code

Claude Code has a native `Artifact` tool. Install this plugin when you want artifacts on
**your own host** instead — to keep them behind your own auth, or to share a URL that is
not tied to a chat session.

```text
/plugin marketplace add iicmaster/artifact-sftp
/plugin install artifact-sftp@artifact-sftp
```

Then run:

```text
/artifact-sftp:artifact-sftp-setup
```

The skills also work linked into your personal skills directory, without the plugin
system:

```bash
git clone https://github.com/iicmaster/artifact-sftp.git
ln -s "$PWD/artifact-sftp/skills/artifact-sftp"       ~/.claude/skills/artifact-sftp
ln -s "$PWD/artifact-sftp/skills/artifact-sftp-setup" ~/.claude/skills/artifact-sftp-setup
ln -s "$PWD/artifact-sftp/skills/artifact-sftp-read"  ~/.claude/skills/artifact-sftp-read
```

Then run `/artifact-sftp-setup`. Artifacts published from Claude Code land under
`/claude/` in the URL path.

## MCP (local stdio)

`artifact-sftp-mcp` is a **local stdio** MCP server. It wraps the existing publisher,
local read resolver, and setup-status contract; it does not expose an HTTP endpoint or
reimplement SFTP. The server keeps stdout exclusively for MCP frames.

Run it from a trusted checkout (Python 3.11+ and `uv` are required):

```bash
export ARTIFACT_SFTP_PLUGIN_ROOT=/absolute/path/to/artifact-sftp
uv run --directory "$ARTIFACT_SFTP_PLUGIN_ROOT" artifact-sftp-mcp
```

Register that exact launch command with an MCP host, including the absolute
`ARTIFACT_SFTP_PLUGIN_ROOT` environment value. Tool calls must pass an absolute
`project_path`; this is the project where `docs/artifacts/` will be kept.

For Codex CLI, the equivalent one-time local registration is:

```bash
codex mcp add artifact-sftp \
  --env ARTIFACT_SFTP_PLUGIN_ROOT=/absolute/path/to/artifact-sftp \
  -- uv run --directory /absolute/path/to/artifact-sftp artifact-sftp-mcp
```

This registers a local stdio process only; it does not put SFTP or Cloudflare
credentials in Codex configuration. Run `codex mcp get artifact-sftp` to review
the registration, or `codex mcp remove artifact-sftp` to remove it.

The v1 tool surface is deliberately small:

- `artifact_sftp.setup_status` checks readiness without writing configuration.
- `artifact_sftp.setup` returns a local-terminal wizard command. It never collects a
  password, Cloudflare token, or private key in MCP arguments.
- `artifact_sftp.publish` accepts a regular project-local `.html`/`.htm` file. It is
  private by default and requires `confirm=true`; public publishing also requires
  `confirm_public=true`. It deliberately has no `--force` or `--allow-sensitive` escape
  hatch.
- `artifact_sftp.read` resolves a canonical URL, `read-back:` line, or local archive path
  and returns a bounded local excerpt. It never WebFetches a private viewer URL; returned
  HTML is marked untrusted and is not a rendering verdict.

For a first local protocol check, run the MCP test suite from the checkout:

```bash
uv run python -m unittest discover -s tests -p 'test_mcp*.py' -v
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
URL. Run the command from the project working directory. The publisher refuses to upload
unless it can first write the stamped bytes to `docs/artifacts/<tool>/<visibility>/<slug>/`;
exit `9` means the local archive gate failed. The last line of successful stdout is always
the artifact URL.

The local layout mirrors the remote artifact identity:

```text
docs/artifacts/codex/private/my-report/index.html
docs/artifacts/codex/private/my-report/my-report--1--20260804T120000Z.html
```

The local archive remains after `--delete`; deleting a remote artifact does not erase local
history. `--dry-run` reports the destination without creating files.

Every published page is stamped with a creation-time footer and gets a UTF-8 declaration
plus `<html lang="...">` when the source HTML lacks them, so non-ASCII text renders
correctly. Optional config keys `DEFAULT_LANG` (default `th`) and `DEFAULT_TIMEZONE`
(default `Asia/Bangkok`) control the page language and the footer time.

Useful operations:

```bash
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh --list --tool codex
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh \
  --slug my-report --tool codex --public --dry-run report.html
bash <plugin-dir>/skills/artifact-sftp/scripts/publish.sh \
  --delete my-report --tool codex
```

## Reading artifacts back

A private artifact's URL is a *viewer* link, not a fetchable resource: the Cloudflare
Zero Trust gate blocks even the publishing account from reading it over HTTP.
Use the `artifact-sftp-read` skill whenever an agent is asked to open, inspect, verify, or
summarize an artifact URL. It resolves the local archive before reading it, so an agent that
just published the file must not stop at an HTTP access error. Read an artifact you published
from the local archive instead:

```text
docs/artifacts/<tool>/<visibility>/<slug>/index.html
docs/artifacts/<tool>/<visibility>/<slug>/<slug>--<version>--<timestamp>.html
```

The URL path encodes the archive path: `https://.../<tool>/<visibility>/<slug>/` maps to
`docs/artifacts/<tool>/<visibility>/<slug>/`. The publish output prints the exact path on
stderr as a parseable `read-back:` line. If the local archive is out of reach (a fresh
session or another machine), use the SFTP path from your config:
`<remote-base>/<tool>/<visibility>/<slug>/index.html`. Never WebFetch the artifact URL to
read it back — it is not fetchable over HTTP.

From the publishing project, the bundled resolver maps either the URL or the `read-back:`
line to an absolute local file path without making a network request:

```bash
path=$(bash <plugin-dir>/skills/artifact-sftp-read/scripts/read-artifact.sh \
  'https://artifacts.example/codex/private/my-report/')
```

See [the setup guide](skills/artifact-sftp/references/setup.md) for server layout,
automation, authentication modes, and Cloudflare Access verification.

## Security model

- Treat publishing as data exfiltration: inspect every artifact before upload.
- Treat `docs/artifacts/` as a local custody copy, not as release or public-delivery proof.
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
python3 tests/test_agent_plugins.py
uv run python -m unittest discover -s tests -p 'test_mcp*.py'
bash skills/artifact-sftp/scripts/test_publish.sh
bash skills/artifact-sftp/scripts/test_setup.sh
bash skills/artifact-sftp-read/scripts/test_read_artifact.sh

for script in skills/artifact-sftp/scripts/*.sh \
  skills/artifact-sftp-setup/scripts/*.sh \
  skills/artifact-sftp-read/scripts/*.sh; do
  bash -n "$script"
done
python3 -m py_compile skills/artifact-sftp/scripts/sftp_helper.py
```

## License

[MIT](LICENSE)
