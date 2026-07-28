# Changelog

All notable changes to this project are documented here.

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
