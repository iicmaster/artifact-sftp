# Changelog

All notable changes to this project are documented here.

## [0.14.0] - 2026-08-15

- Add `artifact_sftp.list` MCP tool to list local artifact archives and discovered workspace HTML drafts in a project (Local-First).
- Add `artifact-groom` skill for project-wide artifact health auditing, categorization (Fresh, Stale, Unlinked, Orphaned, Local Draft), and safe curation.
- Improve `sftp_helper.py` delete operation to properly propagate real permission/IO errors while idempotently handling `ENOENT`.
- Make OpenSSH unpublish/delete truly idempotent using `-rmdir` in batch scripts.
- Scope `PUBLIC_BASE_URL` validation to publish operations, allowing unpublish/delete on unconfigured or legacy viewer URLs.
- Improve `setup.sh` diagnostic classification for invalid `PUBLIC_BASE_URL` in `setup_status`.
- Update `show-me` skill to require explicit user approval before publishing.

## [0.13.0] - 2026-08-15

- Add `artifact_sftp.unpublish` MCP tool to safely remove published HTML artifacts from the remote SFTP host by slug while strictly preserving local archives in `docs/artifacts/`. Supports `confirm=true` (and `confirm_public=true` for public visibility) and `--dry-run` preflight (closes #9).
- Make first-machine Artifact SFTP setup diagnosable through MCP: the packaged launcher now
  fails closed with distinct portable-host errors, `setup_status` returns redacted structured
  local prerequisites, and `verify_connection: true` adds a bounded no-write authenticated SFTP
  preflight without exposing a direct shell fallback.
- Add a complete environment-owner setup guide, clean-home MCP regressions, and clear separation
  between plugin startup, local configuration, and remote SFTP failures.
- Reject malformed `PUBLIC_BASE_URL` values before publish and make 1Password `op.exe` resolution
  consistent with setup status for WSL/Git Bash environments.

## [0.12.0] - 2026-08-15

- Add root `.mcp.json` so Claude Code can start the MCP server. That installer reads a root
  `.mcp.json` or an `mcpServers` field in `.claude-plugin/plugin.json`, and reads neither
  the portable `mcp.json` nor `.codex-plugin/`. Since MCP-only routing landed in 0.11.0 the
  plugin installed and its skills loaded there, but the host reported
  `0 plugin MCP servers` and every `artifact_sftp.*` tool was missing — which agents
  correctly read as a stop condition, so publishing was unreachable on that host.
- The new entry is not a copy of `mcp.json`: Claude Code expands `${CLAUDE_PLUGIN_ROOT}`
  rather than `${PLUGIN_ROOT}`, and does not supply `PLUGIN_DATA`, which the launcher
  requires — without it `bin/artifact-sftp-mcp` exits 78 and the host registers a server
  it never starts. `PLUGIN_DATA` now points outside the plugin directory so the `uv`
  environment survives plugin updates.
- Keep the MCP adapter's own virtualenv out of a child script's `PATH`. Launched by `uv run`,
  the adapter prepends its own virtualenv to `PATH`, which carries only `mcp[cli]`. Subprocess
  scripts resolving `python3` from `PATH` (such as `setup.sh` and `publish.sh`) now correctly
  reach the system or environment interpreter carrying `paramiko`.
- Add the `show-me` skill (adapted from humanlayer's show-me under MIT) to create and publish
  the smallest diagram, table, or visual artifact that makes a point, published directly through
  `artifact_sftp` with a strict "never draw a secret" invariant.

## [0.11.1] - 2026-08-12

- Fix HTML stamping for case-insensitive HTML tag names, including uppercase `HTML`, `HEAD`,
  and `BODY` documents.

## [0.11.0] - 2026-08-12

- Add portable root `mcp.json` discovery and a plugin-relative stdio launcher. AI-agent skills
  and the root policy now require `artifact_sftp.*` MCP routing; unavailable MCP is a stop
  condition rather than a shell, SFTP, or HTTP fallback.
- Make bundled implementation scripts reject ordinary direct invocation, and replace the
  agent-facing setup flow with a pre-provisioned MCP boundary that never requests or relays
  credentials.
- Make [Sarabun](https://fonts.google.com/specimen/Sarabun) the default Thai font in every
  published artifact, using the official Google Fonts stylesheet with `font-display=swap` and
  a Thai-safe fallback stack.

## [0.10.0] - 2026-08-10

- Add a local stdio MCP server (`artifact-sftp-mcp`) with typed `setup_status`, safe
  terminal-only setup instructions, confirmation-gated publishing, and bounded local
  artifact read-back. It delegates to the existing hardened scripts rather than
  reimplementing SFTP, and adds in-memory plus real-child-process stdio tests.

## [0.9.0] - 2026-08-10

- Add the dedicated `artifact-sftp-read` skill and an offline resolver that maps a canonical
  or versioned artifact URL (or the publisher's `read-back:` line) to the local archived bytes.
  Agents can now inspect an artifact they just published without WebFetching a private
  Cloudflare Access viewer URL.
- Add a portable root `plugin.json` targeting Agent Plugins 1.0.0, make all bundled skill
  frontmatter conform to Agent Skills, and validate the portable manifest/skills in CI. The
  existing Codex and Claude packaging files remain compatibility metadata for their installers.
- Fix footer stamping to target the final `</body>` rather than a matching string inside an
  inline script, with a regression test covering a single-line bundled document.

## [0.8.0] - 2026-08-08

- Guarantee the stamped page declares UTF-8 (`<meta charset="utf-8">`) and sets
  `<html lang="...">` when the source HTML lacks them, so non-ASCII text (Thai etc.)
  renders correctly instead of mojibake.
- Enlarge the artifact footer from 12px to 14px and darken it for readability.
- Add `DEFAULT_LANG` (default `th`) and `DEFAULT_TIMEZONE` (default `Asia/Bangkok`) config
  keys: the stamped page language and footer time now follow these instead of a hardcoded
  zone. Set them at setup time with `--lang`/`--timezone` (the wizard prompts for both) or
  by editing the config directly. The footer label now uses the system zone abbreviation
  (`Asia/Bangkok` → `+07`/`ICT` depending on tzdata) via `date '%Z'`.

## [0.7.0] - 2026-08-06

- Replace HTTP basic auth with **Cloudflare Zero Trust** as private-artifact protection.
  Removed the `BASIC_AUTH` config key, the `--basic-auth` setup flag, the wizard prompt,
  and the basic-auth curl verify path — private reads and verification now rely solely on
  a Cloudflare Access service token (`CF_ACCESS_CLIENT_ID`/`CF_ACCESS_CLIENT_SECRET`).
  Migration: remove `BASIC_AUTH` from existing configs (a config that still carries it is
  rejected by `setup.sh --status`) and add the service token to enable HTTP verification.
- Update all docs and marketplace descriptions (SKILL, README, setup guide, archive README)
  to state that private artifacts are protected by Cloudflare Zero Trust.

## [0.6.0] - 2026-08-05

- Document the read-back protocol in SKILL.md: a private artifact's URL cannot be
  fetched over HTTP — basic auth plus the Cloudflare Access gate block even the
  publishing account — so read it back from `docs/artifacts/<tool>/<visibility>/<slug>/`
  or the SFTP path in the config. Proven empirically with A/B tests using real agents:
  with no archive in reach and no documented protocol, agents give up ("cannot read")
  and may even try the wrong SFTP host; with the protocol documented, they identify the
  correct read path immediately.
- Publish output now prints a parseable `read-back: <path>` line on stderr (renamed
  from `local copy:`), so the agent that just published gets the exact local path of
  the upload in hand. The last stdout line remains the artifact URL.

## [0.5.0] - 2026-08-05

- Require every real publish to create a stamped local copy under
  `docs/artifacts/<tool>/<visibility>/<slug>/` before SFTP upload. The publisher exits
  `9` and skips the upload when the local archive path cannot be created or is a symlink.
- Prove `private` instead of asserting it. After a private publish the script now
  re-fetches both `index.html` and the immutable snapshot carrying no credentials;
  if either artifact comes back it exits `7` with take-down instructions, without
  printing the URL. Inconclusive anonymous probes fail closed with exit `8`, and
  the probe disables ambient `curlrc` credentials. Found in the field: a
  `claude/private/` path served the full document to anonymous requests while the
  script reported "readable only with the configured credentials" — the authenticated
  verify had passed, and nothing had ever checked the other half.

## [0.4.1] - 2026-07-31

- Stamp the page footer in Thai local time (`Asia/Bangkok`, labeled ICT) instead
  of UTC. Snapshot filenames stay UTC for machine sorting.

## [0.4.0] - 2026-07-30

- Add Claude Code packaging: `.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`, so the plugin installs with
  `/plugin marketplace add iicmaster/artifact-sftp` and
  `/plugin install artifact-sftp@artifact-sftp`.
- Document Claude Code in the README install section, including the
  personal-skills-directory alternative for setups that do not use the plugin
  system, and note when to prefer it over the native Artifact tool.
- Route Claude Code first-run configuration to the setup skill in `SKILL.md`.
- Bring `.codex-plugin/plugin.json` up to the released version, which had stayed
  at `0.3.0` through the `0.3.1` release.

## [0.3.1] - 2026-07-28

- Accept `claude` as a `--tool` value across publish/setup scripts and docs, so
  artifacts published from Claude Code land under `/claude/` in the URL path.

## [0.3.0] - 2026-07-23

- Add a standalone Codex marketplace manifest and public installation instructions.
- Add the first-run setup skill with guarded credential handling and readiness checks.
- Add cross-platform CI, release-tree secret scanning, security reporting
  guidance, and an MIT license.
- Verify public dry-run, password-auth SFTP connectivity, and offline
  regression suites.

## [0.2.0] - 2026-07-23

- Add the interactive first-run setup command and non-mutating `--status` check.

## [0.1.0] - 2026-07-18

- Initial Codex/OpenClaw plugin with private-by-default SFTP artifact publishing.
