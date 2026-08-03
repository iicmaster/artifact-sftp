# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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
