---
name: artifact-groom
description: Audit, inspect, and groom all HTML artifacts in the project (Local-First). Identifies fresh, stale, and orphaned artifacts, proposing safe updates via artifact_sftp.publish or teardowns via artifact_sftp.unpublish. ใช้เมื่อต้องการตรวจสุขภาพ สังคายนา หรือจัดระเบียบ artifact ทั้งหมดในโปรเจกต์
---

# Artifact Grooming — Local-First Artifact Curator

The `artifact-groom` skill is an MCP-only workflow that audits, inspects, and maintains the health of all HTML artifacts in a project.
It discovers the local custody record (`docs/artifacts/`) and workspace HTML files through `artifact_sftp.list`,
compares published snapshots with current source documents using normalized markup comparison,
and presents an actionable health matrix for updates or cleanups.

## Mandatory routing

1. Use only `artifact_sftp.*` MCP tools (`artifact_sftp.list`, `artifact_sftp.publish`, `artifact_sftp.unpublish`, `artifact_sftp.read`).
2. Never execute, source, or wrap bundled scripts directly.
3. Local-First Invariant: Always start by inspecting the project's local archive through `artifact_sftp.list`.
4. Never perform destructive unpublishing or batch republication without explicit user confirmation.
   - For `private` visibility: requires `confirm=true`.
   - For `public` visibility: requires BOTH `confirm=true` and `confirm_public=true`.

## Grooming workflow

### 1. Inventory Discovery via MCP

Call `artifact_sftp.list` with `project_path` (optional `tool`, `visibility`, and `limit`):

- Inspects all tool namespaces (`codex`, `openclaw`, `claude`) and visibilities (`private`, `public`) in `docs/artifacts/`.
- Retrieves each artifact's `latest_version`, `latest_snapshot`, `snapshot_count`, `mtime`, and `index_sha256`.
- Automatically prunes build, test, and framework cache trees (e.g. `dist/`, `build/`, `coverage/`, `.next/`).
- Returns `local_drafts` listing workspace `.html`/`.htm` files outside artifact archive directories.
- Reports `artifacts_truncated` and `local_drafts_truncated` flags when items exceed `limit` (default: 100).

### 2. Source Matching & Content Normalization

For each discovered artifact in the inventory:

1. **Source Matching:** Search workspace files for candidate source HTML (e.g. matching filename `<slug>.html`, `docs/artifacts/<slug>.html`, or documented source paths).
2. **Content Normalization:**
   - Because the publisher injects defaults during publishing, a raw byte hash will differ from the original source.
   - Strip or account for all publisher-injected elements before comparing content:
     - Google Fonts Sarabun stylesheet link (`<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sarabun...`)
     - Injected Sarabun font style (`<style data-artifact-sftp-font="sarabun">...`)
     - Injected charset declaration (`<meta charset="utf-8">`)
     - Injected language attribute on `<html>` (`lang="th"` / `lang="en"`)
     - Injected metadata footer (`<footer data-artifact-meta...>`)
   - Alternatively, compare normalized DOM body contents or stripped text structures.
3. **Modification Comparison:** Compare normalized source content and file modification timestamps (`mtime`).

### 3. Health Classification Matrix

Classify each item into one of the following states:

| Status | Icon | Criteria | Recommended Agent Action |
|---|---|---|---|
| **Fresh / Synced** | 🟢 | Normalized source matches latest snapshot; up to date | Retain as-is |
| **Stale / Outdated** | 🟡 | Source HTML has newer edits or different normalized content | Propose `artifact_sftp.publish` to update version |
| **Unlinked Source** | ⚪ | Source filename differs from slug; provenance unconfirmed | Keep; prompt user for source path if update needed |
| **Orphaned / Ephemeral** | 🔴 | Known source deleted, or slug matches test prefixes (`test-*`, `smoke-*`, `tmp-*`) | Propose `artifact_sftp.unpublish` with confirmation |
| **Local Draft** | 📝 | Workspace HTML file exists without published archive | Offer initial `artifact_sftp.publish` |

### 4. Present Grooming Report

Render a clear, structured summary table to the user:

```text
| Slug / Path | Tool / Visibility | Version | Last Updated | Status | Recommended Action |
|---|---|---|---|---|---|
| show-me-architecture | openclaw / private | v2 | 2026-08-15 21:13 | 🟢 Fresh | Keep |
| project-summary | codex / private | v1 | 2026-08-10 14:00 | 🟡 Stale | Update (publish) |
| reports/q3-review.html | (local draft) | - | 2026-08-15 10:00 | 📝 Local Draft | Publish |
| smoke-test-1 | openclaw / private | v1 | 2026-08-12 09:30 | 🔴 Ephemeral | Unpublish |
```

### 5. Interactive Execution & Safeguards

Ask the user to confirm proposed actions before executing mutations:

- **For updates:** Call `artifact_sftp.publish(project_path, source_path, slug, tool, visibility, confirm=true)` (add `confirm_public=true` if public).
  - *No redundant verification:* Once publish succeeds, the update is complete. Do not execute follow-up verification calls.
  - *Note on machine ownership:* If the slug was originally published on a different machine, the publisher guards against accidental remote overwrites. Report ownership mismatch if encountered.
- **For teardowns:**
  - Optionally preview with `artifact_sftp.unpublish(project_path, slug, tool, visibility, dry_run=true)`.
  - Execute teardown with `artifact_sftp.unpublish(project_path, slug, tool, visibility, confirm=true)` (add `confirm_public=true` if public).
  - Remind the user that remote hosting is removed while local snapshot history in `docs/artifacts/` is preserved.
