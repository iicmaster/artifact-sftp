# ADR 0002: v1 Project Namespace (`/{project}/{visibility}/{slug}/`) and Preselected Cloudflare R2 Profile

- **Status:** Accepted (implemented per `docs/plans/artifact-sftp-v1.0-spec.md`, RC)
- **Date:** 2026-10-30
- **Deciders:** Master (business requirements: project-first URLs, Cloudflare default for new setups, private/public separation, MCP-only continuity); delegated technical rulings recorded in the spec's decision ledger; cross-vendor advisor review (Codex `gpt-6.1-sol[ultra]`, Gemini `gemini-3.8-flash-high`, receipts `e0036962`/`e2acc267`)

## Context

Canonical artifact identity was `/{tool}/{visibility}/{slug}/` with the generating tool baked into the URL, `project_path` serving only as a local archive boundary, and SFTP as the default backend for config without `STORAGE_DRIVER`. Projects had no identity in URLs, identical names across tools could not share a namespace, and new setups defaulted to SFTP-first semantics.

## Decision

1. **v1 profile marker:** a config key `PROFILE_VERSION=2` explicitly selects v1 semantics. Missing `STORAGE_DRIVER` and package upgrades never imply v1; legacy profiles keep the `/{tool}/…` layout and 100% of their current contract.
2. **Canonical identity (v1):** `(profile, project, visibility, slug)`; URL and object keys are `{project}/{visibility}/{slug}/…`; local archive mirrors it. The MCP argument `slug` keeps its name and `tool` stays optional provenance metadata — neither appears in v1 identity.
3. **Project resolution:** explicit `project` argument → `.artifact-sftp.json` (`{"project": "…"}` at the project root) → structured `project_required` refusal. A mismatch between argument and binding is a hard error; project identifiers are never derived from paths, Git, or hostnames. Grammar reuses the slug rule.
4. **Reserved roots:** while legacy and v1 layouts can coexist on one destination, `codex|openclaw|claude` are refused as v1 project names — `/codex/private/x` is ambiguous between the layouts, and refusing creation is cheaper than physical separation or guessing.
5. **Cloudflare R2 default:** the new-profile flow preselects R2 (`STORAGE_DRIVER=s3`, provider `cloudflare-r2`) as the recommended recipe. It becomes publishable only after owner provisioning; readiness states are reported honestly and publish fails closed (`NOT_READY`-equivalent exits) without fallback to SFTP, AWS, `r2.dev`, or public endpoints. Setup asks for the public base URL with no baked default.
6. **Private pre-flight gate (v1):** before the first upload into a project's private namespace, an anonymous probe of the target URL must demonstrate an Access-style response (`302/401/403`). `200` is a critical exposure failure and anything inconclusive (e.g. a bare `404` from an unprotected origin) refuses publication. The existing post-publish probes remain.
7. **Shared trust domain:** all artifacts served from one origin are one browser trust domain; v1 declares this and forbids untrusted third-party HTML via the artifact-audit gate instead of pretending path prefixes isolate origins.

## Consequences

- Old callers and old profiles keep working unchanged; v1 is strictly opt-in via the marker.
- `read`/`list` accept both layouts; reserved roots keep every path unambiguously interpretable.
- Cloudflare Access wildcard coverage (`/*/private/*`) must be proven on the real tenant during provisioning; until then v1 private publishing fails closed by construction.
- Remote migration is out of scope; a future tool must be explicit, dry-run first, custody-checked, and reversible in its reporting.
