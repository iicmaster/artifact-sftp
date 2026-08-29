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

## GitHub PR & Automated Review Lifecycle

- Do NOT manually request review or tag `@codex review` after push/PR creation; the GitHub Codex bot is automatically triggered on push and PR events.
- Autonomously monitor CI matrix checks and bot review comments.
- Continuously address and resolve all feedback/review comments until 0 active issues remain and all CI checks pass 100%.
