# Changelog
 
All notable changes to this project are documented here.
 
## [0.19.0] - 2026-08-24

- **Mandatory Agent Plugins 1.0.0 Pre-Publish Hard Gate:** Added Dimension 4 check in `artifact-audit` to 🔴 **BLOCK** any manifest schema, MCP configuration, skill frontmatter, or leaked internal script violation. Integrated all 5 conformance checks into first-class pytest test cases (`test_manifest_conformance`, `test_mcp_conformance`, `test_claude_mcp_compatibility_conformance`, `test_skills_conformance`, `test_mcp_only_agent_routing_conformance`).
- **Dynamic Plugin Version Footer Stamping:** Upgraded `publish.sh` to dynamically resolve the plugin version from `plugin.json` and stamp `artifact-sftp vX.Y.Z` into the metadata footer (`<footer data-artifact-meta...>` -> `artifact: <slug> · v<ver> · artifact-sftp v<plugin_ver> · created <timestamp>`). Added publisher test assertion.
- **`show-me` Skill Overhaul (3 Pillars & 4 Depths based on ELI5.cc):**
  - **The 3 Mandatory Pillars (The Triad of Trust):** Every explanation must feature a **Visual Diagram** (SVG/Mermaid/Tree), **Plain Language** (anti-slop prose with analogies beside real names), and **Checkable Sources** (clickable `file:///...#Lxx` source links, configuration keys, or specs).
  - **One Idea, Four Depths (Official ELI5.cc Tiers):** Supports 4 adjustable depth levels: `ELI5` (Level 1, Default — intuition and everyday comparisons), `ELI10` (Level 2 — structured cause-and-effect flow), `ELI15` (Level 3 — system mechanisms, sequence flows, API contracts), and `Expert` (Level 4 — full architecture, invariants, concurrency, failure modes).
  - **Depth Controls:** Added CLI flags `--depth eli5|eli10|eli15|expert` (and `--depth 1..4`), natural language routing, and progressive deepening on follow-up questions.

## [0.18.1] - 2026-08-24

- **100% Borderless Fullscreen Viewport Lightbox:** Upgraded the diagram `<dialog>` lightbox component to a true `100vw × 100vh` borderless Zen canvas, eliminating floating card borders and removing footer waste for maximum vertical viewing space.
- **Interactive Canvas Pan & Zoom Engine:** Implemented CSS transform-based pan-and-zoom (`translate(x, y) scale(s)`) with smooth mouse dragging, mouse wheel zooming centered at the cursor, touch support for mobile, and integrated zoom toolbar (`➕ / ➖ / ↺` + scale indicator badge).
- **Zero-Collision Geometry & Orthogonal Channel Routing:** Established strict layout rules in `visual-illustrator`:
  - Mandatory background `<rect>` pill badges behind all connection label texts to prevent path slicing through text glyphs.
  - Manhattan orthogonal channel routing with dedicated Y-offsets and minimum 20px clearance between parallel lines.
  - Bounding box safety clearances ($\ge 60\text{px}$ horizontal, $\ge 40\text{px}$ vertical).
- **artifact-audit Zero-Collision Gate:** Added Dimension 2 checks that 🔴 **BLOCK** unbadged connection labels, overlapping node bounding boxes, or collinear path collisions.
- **Collision Test Suite:** Added `tests/test_diagram_audit_collision.py` covering clean diagrams, unbadged label blocking, and raw Mermaid blocking.
- **Antigravity Global MCP Registration:** Configured `artifact-sftp` MCP server across Antigravity configuration paths (`~/.gemini/config/mcp_config.json`, `~/.gemini/antigravity/mcp_config.json`, `~/.gemini/antigravity-ide/mcp_config.json`).

## [0.18.0] - 2026-08-24

- Adopt **Option 4 (Static Sanitized Inline SVG Delivery)** for published HTML artifacts, resolving the Mermaid renderer paradox (Issue #21). Mermaid remains the lightweight authoring format for inline chat and pure Markdown documents, while published HTML requires self-contained, sanitized inline SVG.
- Enforce **100% Fit-First Responsive Diagram Layout** (`max-width: 100%`, `overflow: hidden`, strictly no horizontal scrolling on primary diagram cards) to preserve the big-picture overview in published artifacts (Issue #23).
- Introduce **Viewport Lightbox / Expand Detail** (`<dialog>` + `showModal()`) with accessible Zoom In/Out/Reset controls, keyboard navigation (`Esc`), backdrop click, focus trapping, and focus restoration for detail inspection.
- Update `artifact-audit` pre-flight gate with 🔴 **BLOCK** for raw unrendered Mermaid in published HTML, horizontal scrolling on primary diagram overviews, and unsafe SVG content (`<script>`, inline `on*` handlers, external URLs, or colliding IDs); 🟡 **WARN** for complex diagrams (>12 nodes) lacking an Expand Detail trigger.
- Update `skills/visual-illustrator/SKILL.md`, `skills/show-me/SKILL.md`, and `skills/artifact-audit/SKILL.md` to reflect the new diagram ergonomics and audit standards.
- Add formal Technical Specification at `docs/rfcs/rfc-diagram-ergonomics-and-renderer.md`.

## [0.17.3] - 2026-08-22

- Rework `show-me` around comprehension: the skill now aims to make a reader who knows nothing about the topic understand it, with depth treated as a follow-up the reader asks for rather than a default. The posture is adapted from the `eli5` skill (anthropics/claude-plugins-community, MIT), bounded by a rule that an analogy sits beside a real name and never replaces it, so a reader who greps for a term still finds it.
- Make the `artifact-audit` pre-flight gate mandatory in `show-me`. The skill previously published HTML artifacts without mentioning the gate at all, so a diagram could reach SFTP without the quality, link, and secret checks every other publish path enforces.
- Grant standing publish authorization for the `private` + 🟢 PASS case in `show-me` and `artifact-sftp`. That case now calls `artifact_sftp.publish` with `confirm: true` without asking again; 🟡 WARN still requires explicit acknowledgement, 🔴 BLOCK still halts, and `public` is never automatic and always needs `confirm_public: true`.
- Stop `show-me` from naming internal implementation scripts in its call-tree example, matching the MCP-only routing policy the other skills are tested against.
- Reframe the README around the whole document loop — write, tighten, structure, draw, audit, publish, keep — with a table naming the skill that owns each step. The previous opening described a file uploader, which is the last step only.
- List all ten shipped skills in the README, grouped as publishing, document craft, and quality gate. `artifact-audit`, `thai-prose-craft`, `artifact-curator`, `visual-illustrator` and `doc-synchronizer` were absent from it entirely, so half the plugin was undocumented at its front door.
- Move the Skills section above the installer and MCP configuration sections. It sat at line 166, 145 lines below the promise that each step is a skill you can invoke on its own.
- Add `README.th.md`, a Thai companion carrying the concepts, the publish journey, the URL anatomy and the skill roster. It deliberately omits setup, MCP configuration, the security model and maintainer commands, pointing at `README.md` for those, so the two files cannot drift on volatile facts.
- Add a language switcher as the first line of both READMEs.
- Bump the version the MCP server advertises at initialization. `build_server()` hard-coded `0.17.2`, so every client diagnostic identified a 0.17.3 server as 0.17.2.
- Stop `show-me` claiming the published bytes were SHA-256 matched. A private publish with no Cloudflare service token skips authenticated HTTP verification and returns `content: not_independently_byte_verified`; the skill now reports that field as it comes back instead of upgrading it.
- Correct the documented publish order. The secret scan runs before any local archive is written, so a secret-blocked publish leaves nothing under `docs/artifacts/` — the README and the explainer artifact previously showed archival first, sending readers to look for files that were never created.
- Reconcile the MCP server's own publish instruction with the standing-approval policy. It read "needs user approval" while `show-me` and `artifact-sftp` grant that approval in advance for the `private` + PASS case, so an agent received two contradictory rules. The instruction now states what is actually invariant: `confirm=true` is always required, the calling skill may hold standing approval for the private path, and public publishing is never automatic.

## [0.17.2] - 2026-08-18

- Parse the Artifact SFTP config instead of sourcing it. `publish.sh` walked the file through `. "$CONFIG"`, which executed every value as shell: a password containing `$(...)` or a backtick ran as the publishing user, and a stray line such as `PATH=/tmp/evil` silently redirected the helpers the publisher invokes. Values are now split on the first `=` and assigned only for allowlisted keys, and an unrecognized key is rejected.
- Allow any character except CR/LF in `SFTP_PASS`. The shell-safe allowlist was a consequence of sourcing the config, and it locked out passwords containing common metacharacters. Keys that still reach a shell word, a `curl -K` directive, or interpolated HTML keep the original restriction.
- Stop stripping whitespace from config values in `sftp_helper.py`, so a password that begins or ends with a space no longer authenticates with a silently different secret.
- Enforce `artifact-audit` as a mandatory, un-bypassable Pre-Flight Quality & Security Hard Gate in `artifact-sftp` and `artifact-groom`, halting publication whenever critical blockers (secrets, broken Mermaid syntax, dead links) are detected.

## [0.17.1] - 2026-08-18

- Fix author font-family override bug by injecting the default Sarabun typography declaration immediately after opening `<head>` instead of before closing `</head>`.
- Fix latent awk parameter syntax error (`close` keyword renamed to `close_at`) in `stamp_open_head`.
- Prevent version footer stacking on republished read-back copies by removing stale `<footer data-artifact-meta...>` tags before applying the updated metadata footer.
- Allow proactive scaffolding of template configuration with secure permissions (0700/0600) and placeholder keys in `artifact-sftp-setup`, avoiding interactive terminal wizards and protecting credential privacy.

## [0.17.0] - 2026-08-17

- Add `artifact-audit` skill as a pre-flight quality, security, and integrity gatekeeper evaluating Thai prose (anti-slop), Mermaid syntax safety, 3-tier layout, broken links, and secret leakage prevention.
- Upgrade `artifact-groom` skill into an end-to-end 6-stage modernization and publishing suite that diagnoses quality with `artifact-audit`, refactors sources with the specialized DocCraft suite (`thai-prose-craft`, `visual-illustrator`, `artifact-curator`, `doc-synchronizer`), and automatically publishes upgraded versioned snapshots via `artifact_sftp.publish`.
- Integrate pre-flight quality checks with `artifact-audit` into `artifact-sftp` before executing publications.

## [0.16.0] - 2026-08-17

- Add `thai-prose-craft` skill for executive and natural Thai prose editing, anti-AI slop filtering, and authentic bilingual technical terminology.
- Add `artifact-curator` skill for high-impact Markdown artifacts, 3-tier progressive disclosure, scannable callouts/alerts, and comparison tables.
- Add `visual-illustrator` skill for syntax-safe Mermaid diagrams with double-quoting enforcement, microservice/cloud topologies, ERDs, state machines, and enterprise color palettes.
- Add `doc-synchronizer` skill for automated auditing of code-to-docs parity, broken links and anchors, and multi-manifest version synchronization across plugin registries.

## [0.15.0] - 2026-08-17

- Add explicit anti-pattern rules across skills to eliminate redundant post-publish verification calls (no automated read/fetch after publish), optimizing tokens and context window.
- Expose complete draft metadata (`path`, `mtime`, `size`, `sha256`) in `artifact_sftp.list` to power offline artifact grooming within the MCP boundary.
- Bound and paginate `artifact_sftp.list` with `limit: int = 100` parameter, early exit in filesystem walk, directory pruning for build/test/cache trees (`dist`, `build`, `coverage`, `.next`, etc.), and truncation reporting.
- Preserve real deletion permission and transport errors in OpenSSH mode by probing remote directory existence before running deletion batches instead of suppressive flags.
- Break snapshot version tie-breaks deterministically by timestamp `(version, timestamp)` on retried uploads.
- Scope draft discovery directory exclusions strictly to recognized artifact archive directories.
- Detail all publisher-injected mutations (Google Fonts Sarabun link & style, charset, lang attribute, footer) in `artifact-groom` normalization guidance.

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
