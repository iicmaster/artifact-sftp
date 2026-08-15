# Artifact SFTP pre-provisioning boundary

This is an internal ownership note, not an AI-agent workflow. Agents must use only
`artifact_sftp.*` MCP tools and must never follow, reconstruct, or request a shell-based
configuration procedure.

## Environment owner responsibilities

Before an agent can publish, the MCP owner provisions and verifies the following out of band:

- An SFTP account and static web origin with distinct `private` and `public` paths for each
  supported runtime (`codex`, `openclaw`, and `claude`).
- Strict SFTP host-key pinning and a least-privilege account whose upload root is limited to
  the artifact origin.
- Cloudflare Access (or an equivalent authenticated edge policy) that protects every private
  path. A private publish is not accepted as private until its anonymous probes pass.
- A local configuration store with owner-only permissions. The plugin package, MCP arguments,
  project workspace, and artifact HTML must never contain credentials, private keys, passwords,
  or Cloudflare secrets.
- A conformant Agent Plugins host that reads the root `mcp.json`, automatically supplies
  `PLUGIN_ROOT` and writable persistent `PLUGIN_DATA`, starts the packaged launcher, and has a
  compatible `uv` executable on `PATH`. The launcher fails closed when either the host contract
  or `uv` is missing; an AI agent may not install a runtime or substitute another execution path.

## Agent-visible contract

An agent starts with `artifact_sftp.setup_status`.

- `ready: true` permits the requested MCP operation.
- `ready: false` means the agent may call `artifact_sftp.setup` to receive a structured stop
  boundary, then must stop. It must not collect a credential or look for another execution path.
- The MCP server never sends configuration contents, host-key material, passwords, tokens, or
  private-key data back to an agent.

The owner should periodically validate that private paths still require authentication and that
the agent-facing MCP server remains the only configured Artifact SFTP execution surface.
