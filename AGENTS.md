# Artifact SFTP agent policy

Artifact SFTP is MCP-only for AI agents.

- Use only the `artifact_sftp.*` MCP tools for setup status, publishing, and
  read-back.
- Never execute, source, or wrap files under `skills/**/scripts/` for an
  Artifact SFTP operation. Those files are internal implementation invoked by
  the MCP server.
- If the MCP tools are unavailable, stop and report `artifact_sftp MCP is not
  available`; do not substitute a shell command, direct SFTP, or HTTP fetch.
- Do not pass or request credentials, secrets, private keys, or unsafe
  overrides through tool arguments.
- Enforce the mandatory `artifact-audit` pre-flight quality and security gate
  prior to publishing or grooming; never bypass the gate when critical blockers are detected.
