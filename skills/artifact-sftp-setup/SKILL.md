---
name: artifact-sftp-setup
description: Check and bootstrap Artifact SFTP configuration readiness through MCP. AI agents scaffold template configs (0700/0600) with placeholders so users can fill credentials directly, but never solicit or relay secrets in chat. ใช้เมื่อต้องตรวจสอบความพร้อมหรือเตรียมไฟล์คอนฟิกสำหรับ artifact-sftp
---

# Artifact SFTP provisioning boundary — MCP-only & Scaffolding

This skill checks configuration readiness and scaffolds boilerplate configuration files for the
environment owner. It separates **Configuration Structure** (automated/public) from **Secret Values**
(user-only).

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
3. If `local_ready: false` (fresh machine or missing configuration):
   - **Proactively scaffold the configuration template:** Create `$HOME/.config/artifact-sftp/`
     (directory mode `0700`) and generate `$HOME/.config/artifact-sftp/config` (file mode `0600`)
     with standard placeholder keys:
     ```bash
     SFTP_HOST=your-sftp-host.com
     SFTP_USER=your-username
     SFTP_PORT=22
     REMOTE_DIR=/path/to/remote/upload
     PUBLIC_BASE_URL=https://artifacts.yourdomain.com
     DEFAULT_TOOL=codex

     # Set exactly one authentication method:
     SFTP_PASS=YOUR_PASSWORD_HERE
     # SSH_KEY=/path/to/private/key
     # OP_KEY_REF=op://vault/item/private-key
     ```
   - Inform the user that the configuration template has been scaffolded at `$HOME/.config/artifact-sftp/config`
     with secure permissions (`0600`), and instruct them to open the file directly to fill in their SFTP credentials.
   - Do NOT force the user to execute manual interactive setup wizards or terminal question loops.
   - Do NOT ask for, receive, or relay passwords, private keys, or secrets in chat.
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
in an MCP call, a chat response, a log, or a file. Structure and templates are automated;
secret values are strictly entered by the user.
