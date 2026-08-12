---
name: artifact-sftp-setup
description: Check whether pre-provisioned Artifact SFTP configuration is ready through MCP. AI agents MUST use artifact_sftp.setup_status and artifact_sftp.setup only; they must never run setup scripts or collect credentials. ใช้เมื่อต้องตรวจสอบความพร้อมของ artifact-sftp ผ่าน MCP เท่านั้น
---

# Artifact SFTP provisioning boundary — MCP-only

This skill does not configure credentials. Artifact SFTP configuration is pre-provisioned outside
the AI-agent workflow.

## Mandatory routing

1. Call `artifact_sftp.setup_status`.
2. If `ready: true`, report the safe readiness fields only and continue with the requested MCP
   operation.
3. If `ready: false`, call `artifact_sftp.setup` for the structured configuration boundary, then
   stop. Do not invoke a script, open a terminal flow, ask for credentials, or relay secrets.
4. If either MCP tool is unavailable, report `artifact_sftp MCP is not available` and stop.

Never include passwords, Cloudflare secrets, private keys, host-key material, or config contents
in an MCP call, a chat response, a log, or a file. A not-ready result is a safe stop condition,
not permission to bypass the MCP surface.
