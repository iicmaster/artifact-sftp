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

1. Before the first real publish in a session, call `artifact_sftp.setup_status` with
   `verify_connection: true`. It first checks local prerequisites, then performs a bounded,
   no-write SFTP preflight using the owner-managed configuration.
2. If it reports `ready: false`, call `artifact_sftp.setup` with the same
   `verify_connection: true` to obtain the structured boundary. If `local_ready: false`
   (missing config), scaffold the template configuration file (`0600`) as outlined in
   `artifact-sftp-setup` and guide the user to fill in credentials directly, then stop.
   The agent must never solicit or accept secrets in chat.
3. Produce one regular `.html` or `.htm` file inside the selected absolute `project_path`.
   Inline CSS, JavaScript, and application assets. The publisher adds the approved
   [Sarabun](https://fonts.google.com/specimen/Sarabun) stylesheet as the default Thai font;
   do not add other external CDN dependencies.
   - *Pre-Flight Quality Audit:* Run `artifact-audit` on candidate documents before publishing to guarantee clean Thai prose, syntax-safe Mermaid diagrams, and zero secret leakage.
4. Ask for user approval before a real publish. Call `artifact_sftp.publish` with
   `confirm: true` only after that approval. The default visibility is `private`; public
   publishing additionally needs explicit public-sharing approval and `confirm_public: true`.
5. On success, `artifact_sftp.publish` has already completed all necessary validations
   (local custody archival, SFTP atomic upload, SHA-256 integrity match, and privacy protection
   probe). Report the published URL and local read-back reference to the user and complete the turn.
   Do NOT perform redundant post-publish verification (do NOT call `artifact_sftp.read`, and do NOT
   fetch or browse the URL).

## No redundant post-publish verification

- `artifact_sftp.publish` performs complete internal verification before returning:
  - Writes local custody copy and versioned snapshot to `docs/artifacts/`.
  - Atomically delivers bytes over SFTP.
  - Verifies remote SHA-256 byte match over HTTP (for public or authenticated private artifacts).
  - Probes anonymous access to ensure private artifacts are not exposed.
- If `artifact_sftp.publish` succeeds, the publish operation is complete.
- AI agents MUST NOT execute follow-up verification actions:
  - Do NOT call `artifact_sftp.read` to "check" or "verify" what was just published. `artifact_sftp.read` is strictly for reading existing archives when explicitly requested.
  - Do NOT fetch, crawl, or browse the published URL with curl, fetch, or browser tools.
- Simply provide the resulting URL and local read-back reference (`docs/artifacts/<tool>/<visibility>/<slug>/...`) to the user.

## Supported MCP operations

- `artifact_sftp.setup_status` — inspect pre-provisioned readiness without mutation; set
  `verify_connection: true` for its bounded, no-write remote preflight.
- `artifact_sftp.setup` — report the MCP-only configuration/connection boundary; it never
  exposes a shell setup path or accepts credentials.
- `artifact_sftp.publish` — publish one project-local HTML file, private by default.
- `artifact_sftp.unpublish` — remove a published HTML artifact from the remote SFTP host by slug.
  Requires `confirm: true` (and `confirm_public: true` for public artifacts). Local archives
  under `docs/artifacts/` are always retained.
- `artifact_sftp.read` — resolve and read a bounded local archive excerpt with no network fetch.
  Use only when explicitly requested to read/summarize an existing artifact; never as a post-publish check.
- `artifact_sftp.list` — list local artifact archives and discovered workspace HTML drafts in a project
  (Local-First) for auditing and grooming.

The agent surface intentionally has no force, sensitive-content override, or direct remote list
operation. If asked for one, explain that the current MCP policy does not permit it;
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
