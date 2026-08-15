# Fresh-machine setup (environment owner)

This is an operator checklist for installing the Artifact SFTP plugin and
pre-provisioning its local runtime. It is not an AI-agent setup procedure.
AI agents use only the `artifact_sftp.*` MCP tools; they do not run the bundled
shell scripts, open a terminal flow, install dependencies, or receive
credentials.

Keep credentials, private keys, host-key material, and Cloudflare service-token
values out of the repository, MCP arguments, agent prompts, chat transcripts,
and logs. If a diagnostic needs to be shared, share only the redacted
`setup_status` fields and the non-secret error code.

## 1. Prerequisites

Install the plugin through an Agent Plugins-compatible host that can read the
portable `plugin.json` and `mcp.json` manifests and start a local stdio MCP
server. For a conformant stdio host, these are automatic launch-contract
requirements, not extra SFTP values to invent during installation:

- it supplies an absolute `PLUGIN_ROOT` for the installed plugin checkout;
- it creates a writable, persistent `PLUGIN_DATA` directory for this installed
  plugin; and
- it keeps the child process's `HOME` pointed at the owner account that contains
  the pre-provisioned Artifact SFTP configuration.

If a host does not supply `PLUGIN_ROOT` and `PLUGIN_DATA`, it cannot launch a
portable Agent Plugins stdio server correctly. Treat that as a host-support
problem before diagnosing SFTP.

### Claude Code: known-good registration path

These are environment-owner commands, not AI-agent instructions. From a normal
terminal, install the released marketplace (or replace the source with an
absolute path to a checkout while validating a local build):

```bash
claude plugin marketplace add iicmaster/artifact-sftp
claude plugin install artifact-sftp@artifact-sftp
```

Reload Claude Code, then run the health check **from a directory outside the
plugin checkout** so the package's plugin-only `.mcp.json` is not also treated
as a project MCP config:

```bash
cd ~
claude mcp list
```

Expect an `artifact-sftp` plugin MCP entry marked `Connected`. If it instead
reports a launcher error, use the error table below; do not create a second
hand-written project MCP configuration. Start a new Claude Code session and
ask it to call `artifact_sftp.setup_status({"verify_connection": true})`
before its first real publish.

The launcher also requires:

- a `uv` executable on the MCP host process's `PATH` (the current CI baseline
  is `uv 0.12.3`); and
- a Python interpreter compatible with the lockfile (`>=3.11`), supplied by
  the host or by its approved `uv` runtime policy.

The launcher fails closed when `uv`, `PLUGIN_ROOT`, or `PLUGIN_DATA` is
missing. It does not install a runtime or choose a shell fallback. The first
start may need the host's approved package/cache access so `uv run --locked`
can create `${PLUGIN_DATA}/venv`.

The setup-status contract checks a subset of the capabilities used by the
publisher. On a Unix-like machine, provision these in the same environment
visible to the MCP child:

- always: `bash`, `awk`, `sed`, `stat`, `ssh-keygen`, `curl`, and either
  `sha256sum` or `shasum`, plus the standard POSIX file/text utilities used by
  the scripts (`grep`, `mktemp`, `date`, `sort`, `tail`, `tr`, `mkdir`, `mv`,
  and `rm`);
- SSH-key authentication: `sftp` and a readable owner-only private key;
- 1Password key references: `sftp`, `op` (or `op.exe`), and an active approved
  1Password session; or
- password authentication: `python3` with `paramiko` importable by that
  host-side interpreter.

The password-auth dependency is intentionally outside the MCP adapter's
locked `uv` environment. The adapter removes its own virtual-environment
directory from the child `PATH` before running the publisher, so installing
`paramiko` only into the adapter venv does not satisfy `setup_status`.

### Supported host environments

The verified runtime is a Unix-like MCP child on macOS or Linux. Native Windows
processes are not supported because the packaged launcher and publisher require
`bash` plus Unix command-line utilities. On Windows, use a host that launches
the MCP child inside WSL or Git Bash, with the matching Unix-like `HOME`,
`PLUGIN_DATA`, `uv`, and authentication tools all visible to that child. Treat
that interoperability path as an owner-side preflight requirement rather than
assuming a Windows desktop installation alone is sufficient.

The SFTP side must already exist: a least-privilege account, a static web
origin serving the upload root, a verified host key for the exact host and
port, and an access policy that protects every private path. If Cloudflare
Access verification is used, provision both service-token fields or neither.

Before provisioning, collect these non-secret owner inputs explicitly:

- SFTP host name;
- SFTP user name;
- SFTP port;
- remote upload root;
- HTTPS base URL serving that root;
- one authentication method (password, SSH key, or 1Password key reference);
- the independently verified host key/fingerprint for that exact host and port;
- the private-edge policy (Cloudflare Access or an equivalent rule covering
  every private runtime path); and
- the default runtime namespace (`codex`, `openclaw`, or `claude`).

The selected authentication value, private key, 1Password secret reference,
Cloudflare service-token secret, and any customer data are sensitive even when
the surrounding connection inputs are not. Keep those values in the secure
owner-side provisioner only.

## 2. Pre-provision the owner-only configuration

The MCP child reads a fixed per-user location, not a file in this checkout:

```text
$HOME/.config/artifact-sftp/
├── config       # regular file, mode 0600 or 0400
└── known_hosts  # regular file, mode 0600 or 0400
```

The directory must be a real directory with mode `0700`. Neither file may be
a symlink. Use the organization's approved owner-side provisioning or secret
manager process to place these files; do not paste their contents into an
agent conversation. The publisher intentionally does not honor environment
overrides for the configuration path.

`config` must contain exactly one non-empty value for each required key:

| Key | Meaning |
| --- | --- |
| `SFTP_HOST` | SFTP endpoint host name |
| `SFTP_USER` | Least-privilege SFTP account |
| `SFTP_PORT` | Numeric SFTP port |
| `REMOTE_DIR` | Upload root on that account |
| `PUBLIC_BASE_URL` | HTTPS origin serving the upload root; host (and optional numeric port) only, with no path, query, fragment, or trailing `/` |
| `DEFAULT_TOOL` | One of `codex`, `openclaw`, or `claude` |

Configure exactly one authentication key: `SFTP_PASS`, `SSH_KEY`, or
`OP_KEY_REF`. The status check rejects zero or multiple authentication modes.
Optional keys are `CF_ACCESS_CLIENT_ID` plus `CF_ACCESS_CLIENT_SECRET`
(together), `DEFAULT_LANG`, and `DEFAULT_TIMEZONE`.

For the owner-side provisioner, the non-secret structure is:

```text
SFTP_HOST=files.example.com
SFTP_USER=artifact
SFTP_PORT=22
REMOTE_DIR=/srv/www/artifacts
PUBLIC_BASE_URL=https://artifacts.example.com
DEFAULT_TOOL=codex

# Select exactly one of the following; do not put an actual secret in this guide.
SSH_KEY=/absolute/owner-only/path/to/ssh-key
# OP_KEY_REF=op://vault/item/private-key
# SFTP_PASS=<stored-out-of-band>

# Optional pair: set both or neither.
# CF_ACCESS_CLIENT_ID=<stored-out-of-band>
# CF_ACCESS_CLIENT_SECRET=<stored-out-of-band>
```

The template is a schema illustration only. An approved owner-side provisioner
or secret manager must write the real values with the required permissions; an
AI agent must never be asked to fill it in or inspect it.

Values are read both by a shell publisher and by the password-auth helper, so
the owner-side provisioning format must be one-line, shell-safe key/value data
accepted by the package. Do not add duplicate keys, unknown keys, multiline
values, or an environment override for the host key file. Keep the auth value,
private-key path, and 1Password reference private even when the value itself is
not a password.

`known_hosts` must contain valid, pinned key data for the configured endpoint:
the host label for port 22, or `[host]:port` for another port. Never disable
strict host-key checking to make a connection succeed, and never replace a
mismatch without independently verifying the new fingerprint.

The host process must inherit this same `HOME`. A configuration installed for
an interactive shell is invisible if the MCP host runs under another account,
container, sandbox, or service home.

## 3. How the MCP host discovers and starts the server

Discovery and readiness are separate gates. First install/register the plugin
with the host and confirm that its tool list contains the Artifact SFTP MCP
server. The portable [Agent Plugins stdio contract](https://agent-plugins.org/specification)
requires the host to provide a persistent `PLUGIN_ROOT` and `PLUGIN_DATA` to
the launched process. The package also includes a root [`.mcp.json`](../.mcp.json)
compatibility entry for Claude Code; it maps that host's plugin root and
official persistent `${CLAUDE_PLUGIN_DATA}` location to the portable launcher
contract.
A plugin that appears installed but exposes zero Artifact SFTP tools has a
host-discoverability problem; do not treat that as a missing SFTP credential
and do not ask an agent to work around it.

The root [mcp.json](../mcp.json) declares the portable launch contract:

```json
{
  "mcpServers": {
    "artifact-sftp": {
      "type": "stdio",
      "command": "./bin/artifact-sftp-mcp",
      "cwd": "${PLUGIN_ROOT}",
      "env": {
        "ARTIFACT_SFTP_PLUGIN_ROOT": "${PLUGIN_ROOT}"
      }
    }
  }
}
```

A conformant portable host supplies `PLUGIN_ROOT` and `PLUGIN_DATA` in the
child environment; `PLUGIN_DATA` is deliberately host-owned runtime storage
and is not the SFTP configuration directory. The launcher then:

1. verifies that the trusted root contains `plugin.json` and `pyproject.toml`;
2. requires a writable `PLUGIN_DATA` and creates its `venv` directory;
3. requires `uv` on the host process `PATH`;
4. runs the locked project entry point `artifact-sftp-mcp`; and
5. keeps stdout exclusively for MCP JSON-RPC frames.

There is no HTTP MCP endpoint. The host owns the process lifecycle and should
restart or reload it after changing the installed checkout or its environment.
Do not wrap the launcher in a shell that writes banners to stdout. Do not
invoke `skills/**/scripts/` as an alternative launch path.

## 4. Test setup through MCP

After installing/registering the plugin and restarting or reloading the host,
confirm the expected tool names in the host's MCP tool list, then use that
host's MCP inspector/tool tester to call:

```text
artifact_sftp.setup_status({"verify_connection": true})
```

This call does not write configuration, artifacts, or remote files. It first
checks local prerequisites and, only when those pass, opens a bounded,
no-write authenticated SFTP preflight through the stored owner configuration. A
healthy, provisioned result contains the safe fields below and includes `READY`
in `diagnostics`:

```json
{
  "ok": true,
  "operation": "setup_status",
  "exit_code": 0,
  "result": {
    "ready": true,
    "local_ready": true,
    "auth_mode": "ssh-key",
    "default_tool": "codex",
    "remote_connection": {
      "status": "verified",
      "operation": "authenticated_sftp_preflight"
    },
    "agent_action": "continue",
    "configuration_required": false
  }
}
```

The exact `diagnostics` list is host-dependent and is redacted by the MCP
adapter. Do not replace it with a dump of `config` or `known_hosts`.

If the result has `local_ready: false`, it normally remains an MCP-successful
result with `exit_code: 3`, `agent_action: "stop"`, and
`configuration_required: true`. If `local_ready: true` but `ready: false`, the
stored local prerequisites passed and the `remote_connection` object explains
the safe preflight outcome. The agent may call
`artifact_sftp.setup({"verify_connection": true})` to receive the structured
boundary and must then stop. Repair the owner-side files/dependencies or the
reported remote boundary, then call `setup_status` again through MCP. A
not-ready result is not permission to run a setup script or collect a
credential from the agent.

## 5. Diagnose “cannot connect”

First classify which connection failed. A host that cannot start the MCP child
and a publisher that cannot reach the SFTP server are different failures.

| Symptom | Meaning | Owner-side next check |
| --- | --- | --- |
| No tools are listed; the host says it cannot connect to the MCP server | Local launcher or stdio startup failed | Confirm the installed package contains the launcher and lockfile, the host is Agent Plugins-conformant (it supplies `PLUGIN_ROOT` and writable persistent `PLUGIN_DATA`), the child `HOME` is correct, and `uv` is on the MCP process `PATH`. |
| Launcher reports `plugin host did not provide PLUGIN_ROOT` | Host did not meet the portable stdio launch contract | Use a conformant host integration or repair its installed-plugin registration, then reload it. |
| Launcher reports `trusted plugin root is unavailable` | The host-supplied `PLUGIN_ROOT` does not contain the trusted package files | Repair the host's installed-plugin path and reload it. |
| Launcher reports `plugin host did not provide PLUGIN_DATA` | Host did not meet the portable stdio launch contract | Use a conformant host integration or repair its per-plugin persistent-data setup; do not use the SFTP config directory as a substitute. |
| Launcher reports `MCP owner must pre-provision uv on PATH` | `uv` is not visible to the MCP child | Provision a compatible `uv` for the host service and restart it; the agent must not install one. |
| `artifact_sftp.setup_status` is available but returns `local_ready: false` | The MCP server is connected; local provisioning is incomplete or unsafe | Use only the redacted diagnostics. Check the fixed config/host-key paths, modes, required keys, one auth mode, host-key match, and the dependency named by the diagnostic. |
| `local_ready: true`, `ready: false`, and `remote_connection.status: "failed"` | Local prerequisites passed but the pinned, authenticated SFTP preflight failed | Repair the endpoint, route/firewall, pinned host key, account authorization, or remote SFTP service using the owner's approved operational checks; do not pass secrets to the agent. |
| `ready: true`, then publish returns `config_or_auth_failed` (exit 3) | The publisher rejected configuration or authentication at operation time | Re-run `setup_status` with `verify_connection: true` under the same MCP host account and repair the owner-side auth/dependency boundary. Do not ask the agent for the secret. |
| Publish returns `remote_operation_failed` (exit 5) | The MCP process ran, but an SFTP operation failed | Verify the host/port, firewall or route, pinned host key, account authorization, remote directory, and remote storage state using the owner's approved operational checks. Do not use direct SFTP or HTTP from the agent. |
| Publish returns `command_timed_out` | A trusted local command exceeded its timeout, often while waiting on a host or network | Check local network reachability and the SFTP endpoint before retrying once; do not retry blindly. |
| Publish or status returns `command_unavailable` | A trusted local command could not be started | Check the shell, executable dependencies, and trusted plugin checkout; reload the host after repair. |

Without `verify_connection`, `setup_status` cannot prove remote reachability
or credentials accepted by the server. With it, the no-write preflight proves
the pinned authenticated SFTP connection only—not remote directory permission,
remote write permission, HTTP availability, private-path protection, remote
byte identity, rendering, or publication approval. An approved publish remains
the first remote write and must still go only through `artifact_sftp.publish`;
that MCP workflow does not authorize direct SFTP, WebFetch, or a bundled script.

## Known boundaries

- `PLUGIN_ROOT` and `PLUGIN_DATA` are reserved, host-supplied variables in the
  portable Agent Plugins stdio contract; `mcp.json` deliberately does not set
  them. A host that omits either variable is not a usable portable host for
  this plugin.
- Password authentication depends on owner-managed `python3` plus `paramiko`,
  separate from the locked MCP adapter environment. `setup_status` reports the
  missing dependency but cannot install it.
- The MCP protocol does not standardize the host UI's generic “cannot connect”
  message. When no tool is available, the host's redacted process/stderr log
  and launch environment are the authoritative startup diagnostics.
- Claude Code reads the root `.mcp.json` in plugin context when the plugin is
  installed. Do not treat the source checkout itself as a project MCP config:
  project scope does not define the plugin-only `CLAUDE_PLUGIN_ROOT` and
  `CLAUDE_PLUGIN_DATA` variables. Validate it through the installed plugin.
- A green local readiness check is not release, publication, privacy, or remote
  byte-identity approval. Keep those claims separate from this onboarding
  smoke test.
