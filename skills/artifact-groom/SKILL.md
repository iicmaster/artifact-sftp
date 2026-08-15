---
name: artifact-groom
description: Audit, inspect, and groom all HTML artifacts in the project (Local-First). Identifies fresh, stale, and orphaned artifacts, proposing safe updates via artifact_sftp.publish or teardowns via artifact_sftp.unpublish. ใช้เมื่อต้องการตรวจสุขภาพ สังคายนา หรือจัดระเบียบ artifact ทั้งหมดในโปรเจกต์
---

# Artifact Grooming — Local-First Artifact Curator

The `artifact-groom` skill is an MCP-only workflow that audits and maintains the health of all HTML artifacts in a project.
It inspects the local custody record (`docs/artifacts/`), compares published snapshots with
current source documents, and presents an actionable health matrix for updates or cleanups.

## Mandatory routing

1. Use only `artifact_sftp.*` MCP tools for any Artifact SFTP mutation or inspection.
2. Never execute, source, or wrap bundled scripts directly.
3. Local-First Invariant: Always build the artifact inventory from the local project archive
   under `docs/artifacts/<tool>/<visibility>/<slug>/`.
4. Never perform destructive unpublishing or batch republication without explicit user confirmation.

## Grooming workflow

### 1. Inventory Discovery (Local-First)

Scan the local project tree under `docs/artifacts/`:

- Identify every tool namespace (`codex`, `openclaw`, `claude`) and visibility (`private`, `public`).
- For each slug directory `docs/artifacts/<tool>/<visibility>/<slug>/`:
  - Locate `index.html` (the current live copy).
  - Find all snapshot files (`<slug>--<version>--<timestamp>.html`) and identify the latest version number.
  - Record the latest snapshot timestamp and SHA256 content digest.

### 2. Source Matching & Comparison

For each discovered slug:

- Search the project workspace for the corresponding source HTML file (for example, `docs/artifacts/<slug>.html`,
  `<slug>.html`, or source files specified in project documentation).
- If source HTML is found:
  - Compare the source file's SHA256 digest with the latest archived snapshot's SHA256 digest.
  - Compare file modification timestamps (`mtime`).
- If no source HTML is found:
  - Check whether the slug matches temporary test patterns (e.g. `test-*`, `smoke-*`, `tmp-*`, `temp-*`).

### 3. Health Classification Matrix

Classify each artifact into one of four states:

| Status | Icon | Criteria | Recommended Agent Action |
|---|---|---|---|
| **Fresh / Synced** | 🟢 | Source matches latest snapshot hash; up to date | Retain as-is |
| **Stale / Outdated** | 🟡 | Source HTML has newer edits or different hash | Propose `artifact_sftp.publish` to update version |
| **Orphaned / Ephemeral** | 🔴 | Source file missing, or slug has temporary test prefix | Propose `artifact_sftp.unpublish` to clean up remote slug |
| **Local Draft** | ⚪ | Source HTML exists locally without published remote state | Offer initial `artifact_sftp.publish` |

### 4. Present Grooming Report

Render a clear summary table to the user:

```text
| Slug | Tool / Vis | Version | Last Published | Status | Recommended Action |
|---|---|---|---|---|---|
| show-me-architecture | openclaw / private | v2 | 2026-08-15 21:13 | 🟢 Fresh | Keep |
| project-summary | codex / private | v1 | 2026-08-10 14:00 | 🟡 Stale | Update (publish) |
| test-experiment | openclaw / private | v1 | 2026-08-12 09:30 | 🔴 Orphaned | Take down (unpublish) |
```

### 5. Interactive Execution

Ask the user which proposed actions to execute:

- **For updates:** Call `artifact_sftp.publish` with `confirm: true` using the updated source path.
- **For teardowns:**
  - Optionally preview with `artifact_sftp.unpublish(..., dry_run=true)`.
  - Execute teardown with `artifact_sftp.unpublish(..., confirm=true)`.
  - Note to the user that remote hosting is removed while local snapshot history is preserved.
