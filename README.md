# Artifact SFTP

Artifact SFTP is a Codex and OpenClaw plugin for publishing one HTML artifact to your
own SFTP-backed web host. It returns a stable URL, keeps versioned snapshots, defaults
to private visibility, and applies [Sarabun](https://fonts.google.com/specimen/Sarabun)
as the default Thai font.

The repository contains no hosting credentials and does not grant access to the
maintainer's deployment. You need an SFTP account and a web server that serves its
upload directory.

## What it does

- Publishes a single HTML file to a stable URL. HTML, JavaScript, and application assets stay
  inline; the publisher adds the official Sarabun Google Fonts stylesheet as the one default
  external runtime dependency.
- Keeps immutable timestamped versions beside the current `index.html`.
- Keeps the stamped current file and snapshot in `docs/artifacts/<tool>/<visibility>/<slug>/`
  before any SFTP upload.
- Exposes publishing and local read-back to AI agents through a local stdio MCP server.
- Separates runtimes (`codex`, `openclaw`, `claude`), and `private` and `public`, in the URL path.
- Pins and verifies the SFTP host key.
- Supports SSH keys, 1Password SSH-key references, or password authentication through
  Paramiko.
- Blocks common secret patterns before upload and verifies public content by SHA-256.
- Keeps provisioning outside the AI-agent workflow; agents only inspect readiness through MCP.

## Agent Plugins compatibility

The portable package root is [plugin.json](plugin.json), which targets the Agent Plugins
1.0.0 schema. [mcp.json](mcp.json) is the portable MCP discovery entry; the immediate
`skills/` children are MCP-routing instructions for AI agents. The existing `.codex-plugin/`
and `.claude-plugin/` files are compatibility metadata for their current installers.

[.mcp.json](.mcp.json) is the Claude Code compatibility entry. That installer discovers a
plugin's MCP servers from a root `.mcp.json` or an `mcpServers` field in
`.claude-plugin/plugin.json`, and reads neither the portable `mcp.json` nor
`.codex-plugin/`. Without it the plugin installs and its skills load, but the host reports
`0 plugin MCP servers` and every `artifact_sftp.*` tool is missing.

It is **not** a copy of `mcp.json`, because Claude Code is not an Agent Plugins host and
supplies a different environment. Three differences are load-bearing:

| | `mcp.json` (Agent Plugins) | `.mcp.json` (Claude Code) |
|---|---|---|
| plugin root variable | `${PLUGIN_ROOT}` | `${CLAUDE_PLUGIN_ROOT}` — the only one this host expands |
| `command` | `./bin/...`, relative to `cwd` | absolute via `${CLAUDE_PLUGIN_ROOT}` |
| `PLUGIN_DATA` | supplied by the host | **not supplied** — must be set here |

`PLUGIN_DATA` is the sharpest one: [bin/artifact-sftp-mcp](bin/artifact-sftp-mcp) exits 78
immediately when it is unset, so the host registers the server, starts nothing, and exposes
no tools. It points outside the plugin directory so the `uv` environment survives plugin
updates. `PLUGIN_ROOT` is also exported for the launcher's own fallback chain.

When the server definition changes, update both files — they are deliberately not identical,
so a plain `diff` should show exactly the rows above and nothing else.

## Fresh-machine onboarding

The environment owner should follow [docs/setup.md](docs/setup.md) before handing this
plugin to an agent. It covers the host prerequisites, the owner-only configuration location,
the stdio launch contract, an MCP-only setup/connection smoke test, and the distinction between
an MCP startup failure and a remote SFTP failure. The checkout is not a credential store: do not put
the configuration, private keys, host-key material, passwords, or Cloudflare secrets in Git,
an MCP argument, an agent prompt, or a log.

The packaged runtime is verified for a Unix-like MCP child on macOS or Linux. Native Windows
processes are not supported; a Windows owner must use a host that launches the child inside WSL
or Git Bash with the same Unix-like `HOME` and required tools. See the setup checklist before
assuming a desktop plugin installation also provisions SFTP access.

Plugin discoverability is a host-registration concern, separate from configuration readiness.
The package includes a Claude Code compatibility [`.mcp.json`](.mcp.json) in addition to the
portable [mcp.json](mcp.json); the two have different host-variable contracts. The Claude entry
uses its official persistent `${CLAUDE_PLUGIN_DATA}` location for the locked runtime, so a plugin
update does not discard it. If the plugin looks installed but the host lists zero Artifact SFTP
tools, reload/approve the host registration first; `setup_status` cannot run until the MCP server
is discoverable. A conformant Agent Plugins host supplies the portable `PLUGIN_ROOT` and
`PLUGIN_DATA` variables automatically; a host that omits either one has a plugin-launch problem,
not an SFTP credential problem.

For the current Claude Code CLI, the environment owner installs the marketplace with
`claude plugin marketplace add iicmaster/artifact-sftp`, then runs
`claude plugin install artifact-sftp@artifact-sftp`. Reload Claude Code and run `claude mcp list`
outside the plugin checkout; the expected plugin server state is `Connected`. The full
copy-paste flow and failure triage are in [docs/setup.md](docs/setup.md).

## MCP (local stdio)

`artifact-sftp-mcp` is a **local stdio** MCP server. It wraps the existing publisher,
local read resolver, and setup-status contract; it does not expose an HTTP endpoint or
reimplement SFTP. The server keeps stdout exclusively for MCP frames.

This package is **MCP-only for AI agents**. A compatible Agent Plugins host discovers the
plugin-relative launcher in [mcp.json](mcp.json), supplies `PLUGIN_ROOT` and a writable
persisted `PLUGIN_DATA` directory, and starts the server. Those two variables are part of the
portable host contract rather than values an installer needs to guess. The manifest starts
`./bin/artifact-sftp-mcp` with `${PLUGIN_ROOT}` as its working directory and passes
`ARTIFACT_SFTP_PLUGIN_ROOT=${PLUGIN_ROOT}`. `PLUGIN_DATA` is a host-owned runtime/cache
directory, separate from the SFTP configuration. The launcher uses the lockfile with `uv` and
does not store credentials in package metadata or MCP arguments.

The pre-provisioned SFTP configuration is read from the MCP process's home directory at
`$HOME/.config/artifact-sftp/config`, with the pinned host keys in the sibling
`known_hosts` file. The MCP host must launch the child with the same owner home directory that
contains those files; an isolated or different `HOME` will correctly appear unconfigured.

The environment owner must pre-provision a compatible `uv` executable on `PATH` (CI verifies
the packaged launcher with `uv 0.12.3`). If it is absent, the launcher fails closed with exit
78; an AI agent must report that boundary rather than installing a runtime or using a fallback.

Tool calls must pass an absolute `project_path`; this is the project where
`docs/artifacts/` will be kept. If the MCP server is not available or reports a configuration
boundary, the agent must stop rather than execute a bundled script, direct SFTP, or HTTP
fallback.

If a host reports that it cannot connect before any tools are listed, diagnose the launcher
environment (plugin root, writable plugin data, `uv`, and the host's MCP process scope) using
[docs/setup.md](docs/setup.md). If `artifact_sftp.setup_status` is available but returns
`ready: false`, the MCP server is connected. Use `verify_connection: true` on a fresh machine:
it adds a bounded, no-write SFTP preflight using only the stored owner configuration. A result
with `local_ready: true` and a failed `remote_connection` points to the SFTP boundary rather
than MCP discovery or local configuration.

The MCP-only policy and internal direct-invocation guards prevent ordinary routing mistakes.
They are not a privilege boundary against a process that already has unrestricted shell and
filesystem access; enforce that stronger boundary in the AI host's tool or sandbox policy.

The agent tool surface is deliberately small:

- `artifact_sftp.setup_status` checks readiness without writing configuration.
- `artifact_sftp.setup` reports the pre-provisioning boundary. It never exposes a terminal
  command or collects a password, Cloudflare token, or private key.
- `artifact_sftp.publish` accepts a regular project-local `.html`/`.htm` file. It is
  private by default and requires `confirm=true`; public publishing also requires
  `confirm_public=true`. It deliberately has no `--force` or `--allow-sensitive` escape
  hatch.
- `artifact_sftp.read` resolves a canonical URL, `read-back:` line, or local archive path
  and returns a bounded local excerpt. It never WebFetches a private viewer URL; returned
  HTML is marked untrusted and is not a rendering verdict.

## Agent workflow

Call `artifact_sftp.setup_status` with `verify_connection: true` before a first real publish.
A ready result has `agent_action: "continue"`; a not-ready result has `agent_action: "stop"`.
`local_ready: false` means the owner-side configuration/dependency boundary needs repair;
`local_ready: true` plus a failed remote preflight means the SFTP boundary needs repair. When
ready, call
`artifact_sftp.publish` only after the required confirmation. The default is private; public
visibility needs a separate confirmation. The MCP server refuses to publish unless it first
writes the stamped bytes to `docs/artifacts/<tool>/<visibility>/<slug>/`.

When setup is not ready, call `artifact_sftp.setup` only to receive its structured boundary,
then stop. Do not ask an agent to inspect or paste the config, run a bundled setup script,
install a dependency, or try direct SFTP/HTTP. The environment owner repairs the boundary and
the agent re-runs `setup_status` through MCP.

The local layout mirrors the remote artifact identity:

```text
docs/artifacts/codex/private/my-report/index.html
docs/artifacts/codex/private/my-report/my-report--1--20260804T120000Z.html
```

`dry_run: true` reports the destination without creating files. The current agent MCP policy
does not expose force, sensitive-content override, list, or delete operations.

Every published page is stamped with a creation-time footer and gets a UTF-8 declaration
plus `<html lang="...">` when the source HTML lacks them, so non-ASCII text renders
correctly. It also receives the official Sarabun Google Fonts stylesheet with `font-display=swap`
and a Thai-safe fallback stack; this is the only default external runtime request. Optional config
keys `DEFAULT_LANG` (default `th`) and `DEFAULT_TIMEZONE` (default `Asia/Bangkok`) control the
page language and the footer time.

## Reading artifacts back

A private artifact's URL is a *viewer* link, not a fetchable resource: the Cloudflare
Zero Trust gate blocks even the publishing account from reading it over HTTP.
Use `artifact_sftp.read` whenever an agent is asked to open, inspect, verify, or summarize an
artifact URL. It resolves the local archive before reading it, so an agent that just published
the file must not stop at an HTTP access error. Read an artifact from the local archive instead:

```text
docs/artifacts/<tool>/<visibility>/<slug>/index.html
docs/artifacts/<tool>/<visibility>/<slug>/<slug>--<version>--<timestamp>.html
```

The URL path encodes the archive path: `https://.../<tool>/<visibility>/<slug>/` maps to
`docs/artifacts/<tool>/<visibility>/<slug>/`. Pass the URL or exact `read-back:` value to the
MCP tool. Never WebFetch the artifact URL or use SFTP as a read fallback.

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
- The agent-facing MCP surface has no sensitive-content override.

For vulnerability reports, follow [SECURITY.md](SECURITY.md).

## Maintainer development

The following are maintainer-only implementation regressions, not AI-agent operational
fallbacks. The test suites are offline: they replace SFTP and HTTP clients with throwaway mocks
and never read the real local configuration.

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
