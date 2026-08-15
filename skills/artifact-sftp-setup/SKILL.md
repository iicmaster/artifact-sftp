---
name: artifact-sftp-setup
description: Check whether pre-provisioned Artifact SFTP configuration is ready through MCP. AI agents MUST use artifact_sftp.setup_status and artifact_sftp.setup only; they must never run setup scripts or collect credentials. ใช้เมื่อต้องตรวจสอบความพร้อมของ artifact-sftp ผ่าน MCP เท่านั้น
---

# Artifact SFTP provisioning boundary — MCP-only

This skill does not configure credentials. Artifact SFTP configuration is pre-provisioned outside
the AI-agent workflow.

Host discoverability and configuration readiness are separate. If the host does not list
`artifact_sftp.setup_status` at all, report `artifact_sftp MCP is not available` and stop; do not
infer that SFTP configuration is missing. The environment owner must repair the host/plugin
registration (the package includes a Claude Code root `.mcp.json` compatibility entry) before
an agent can call this skill.

## Mandatory routing

1. On a fresh machine or before the first real publish in a session, call
   `artifact_sftp.setup_status` with `verify_connection: true`.
2. If `ready: true`, report only the safe readiness fields and continue with the requested MCP
   operation. This proves the local prerequisites and a bounded, no-write SFTP preflight;
   it does not publish, change configuration, create an artifact archive, or change remote
   state. The implementation may create and remove secure temporary files while authenticating.
3. If `local_ready: false`, call `artifact_sftp.setup` for the structured configuration boundary,
   then stop. Do not invoke a script, open a terminal flow, ask for credentials, or relay secrets.
4. If `local_ready: true` but `ready: false`, the stored configuration exists but the requested
   no-write SFTP preflight failed. Call `artifact_sftp.setup` with
   `verify_connection: true`, preserve only its safe error code, and stop.
5. If either MCP tool is unavailable, report `artifact_sftp MCP is not available` and stop.

Without `verify_connection`, `ready: true` means only that local owner-side configuration and
checked dependencies pass. With it, `remote_connection.status: "verified"` additionally proves
the bounded SFTP preflight. Neither result proves HTTP availability, private-edge protection,
remote byte identity, rendering, or publication approval.

If `ready: false`, preserve only the safe, redacted diagnostics. `config`/`known_hosts` paths or
contents and secret values are not agent data. The owner should use [the fresh-machine setup
checklist](../../docs/setup.md) to repair the fixed `$HOME/.config/artifact-sftp/` boundary or the
reported remote preflight code; an agent must not ask for the host, user, password, private key,
host-key material, Cloudflare token, or config contents in chat.

Never include passwords, Cloudflare secrets, private keys, host-key material, or config contents
in an MCP call, a chat response, a log, or a file. A not-ready result is a safe stop condition,
not permission to bypass the MCP surface.
