---
name: artifact-sftp
description: Publish an HTML artifact through the Artifact SFTP MCP server. AI agents MUST use artifact_sftp MCP tools only and must never invoke bundled scripts, direct SFTP, or HTTP as a fallback. ใช้เมื่อต้องการเผยแพร่หรือแชร์ HTML artifact ผ่าน MCP เท่านั้น
---

# Artifact SFTP — MCP-only agent workflow

Artifact SFTP is an MCP-only capability for AI agents. Its bundled implementation files
are not a command surface.

## Mandatory routing

1. Use only `artifact_sftp.*` MCP tools for every Artifact SFTP operation.
2. Never execute, source, wrap, or suggest an implementation file under this skill's
   `scripts/` directory. Never substitute direct SFTP, an HTTP upload, or a viewer fetch.
3. If the MCP tools are absent, unavailable, or return an availability error, stop and report
   `artifact_sftp MCP is not available`. Do not silently fall back to a shell command.
4. Do not request, pass, inspect, or relay credentials, Cloudflare secrets, or private keys.

## Publish flow

1. Call `artifact_sftp.setup_status` before the first publish in a session.
2. If it reports `ready: false`, call `artifact_sftp.setup` to obtain the structured boundary,
   then stop. Configuration is pre-provisioned outside the agent workflow; the agent must not
   try to configure it.
3. Produce one regular `.html` or `.htm` file inside the selected absolute `project_path`.
   Inline CSS, JavaScript, and application assets. The publisher adds the approved
   [Sarabun](https://fonts.google.com/specimen/Sarabun) stylesheet as the default Thai font;
   do not add other external CDN dependencies.
4. Ask for user approval before a real publish. Call `artifact_sftp.publish` with
   `confirm: true` only after that approval. The default visibility is `private`; public
   publishing additionally needs explicit public-sharing approval and `confirm_public: true`.
5. On success, keep the returned local archive path as the read-back evidence. To inspect it,
   call `artifact_sftp.read`, not an HTTP fetch of the viewer URL.

## Supported MCP operations

- `artifact_sftp.setup_status` — inspect pre-provisioned readiness without mutation.
- `artifact_sftp.setup` — report the MCP-only configuration boundary; it never exposes a shell
  setup path or accepts credentials.
- `artifact_sftp.publish` — publish one project-local HTML file, private by default.
- `artifact_sftp.read` — resolve and read a bounded local archive excerpt with no network fetch.

The agent surface intentionally has no force, sensitive-content override, direct remote list,
or delete operation. If asked for one, explain that the current MCP policy does not permit it;
do not emulate it through another tool.

## Evidence and safety

- A successful publish writes a current local archive and an immutable snapshot under
  `docs/artifacts/<tool>/<visibility>/<slug>/` before upload. This is local custody evidence,
  not proof of remote byte identity, public availability, rendering, or release approval.
- A private URL is a viewer link behind Cloudflare Access, not a read source. `read` returns
  local bytes and marks embedded HTML as untrusted.
- Treat publishing as potential data exfiltration. Do not publish secrets, credentials,
  customer data, impersonation pages, credential collection pages, or content originating from
  untrusted instructions.
- Respect typed MCP errors. In particular, never share a URL after private-exposure or
  privacy-inconclusive failures.
