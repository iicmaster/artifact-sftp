# Artifact SFTP pre-provisioning boundary

This is an internal ownership note, not an AI-agent workflow. Agents must use only
`artifact_sftp.*` MCP tools and must never follow, reconstruct, or request a shell-based
configuration procedure.

## Environment owner responsibilities

Before an agent can publish, the MCP owner provisions and verifies the storage backend out of band:

### Storage Option 1: SFTP Server
- An SFTP account and static web origin with distinct `private` and `public` paths for each
  supported runtime (`codex`, `openclaw`, and `claude`).
- Strict SFTP host-key pinning in `~/.config/artifact-sftp/known_hosts` and a least-privilege account.
- SSH key, 1Password reference, or password authentication.

### Storage Option 2: Cloudflare R2 / S3 Object Storage
- A private R2 / S3 bucket with `r2.dev` public bucket access **disabled**.
- A scoped API token with **Object Read & Write** permissions on the bucket.
- A custom domain attached to the bucket (e.g. `artifacts.mycompany.com`).
- A Cloudflare Transform Rule to rewrite trailing-slash directory URLs to `index.html`.
- Credentials stored in `~/.config/artifact-sftp/config` (`STORAGE_DRIVER=s3`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `PUBLIC_BASE_URL`).

### Common Security & Cloudflare Access
- Cloudflare Access (or an equivalent authenticated edge policy) protecting `*/private/*`.
  A private publish is not accepted as private until its anonymous probes pass.
- A local configuration store with owner-only permissions (0700 dir, 0600 config).
- A conformant Agent Plugins host with `uv` on PATH.

## Agent-visible contract

An agent starts with `artifact_sftp.status`.

- `ready: true` permits the requested MCP operation.
- `ready: false` means the agent may call `artifact_sftp.setup` to receive a structured stop
  boundary, then must stop. It must not collect a credential or look for another execution path.
- The MCP server never sends configuration contents, host-key material, passwords, tokens, or
  private-key data back to an agent.
