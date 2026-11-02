# R2 v1 Provisioning Runbook — bring this machine onto the Cloudflare R2 profile

**Status:** waiting on owner-side dashboard + terminal steps (agent is MCP-only per `AGENTS.md`)
**Ruling:** party decision `C → B → D` (two vendor lanes converged; Option A rejected unanimously)
**Snapshot date:** 2026-11-02

---

## 1. Verified state (read-only, 2026-11-02)

| Fact | Evidence |
|---|---|
| Active profile is still **legacy SFTP** (password auth), READY, remote preflight `verified` | `artifact_sftp.setup(verify_connection=true)` → `auth: password`, `READY`, `remote_connection.status: verified`; no `PROFILE_VERSION` line |
| R2 bucket **`pundai`** exists (APAC, Standard, created 2024-05-29), no `r2.dev` indication | `GET /accounts/{id}/r2/buckets` + `/r2/buckets/pundai` |
| Access app **`Artifacts all tools private`** already covers `artifacts.ngs.bz/*/private/*` | `GET /accounts/{id}/access/apps` |
| **No** Access app for a new R2 hostname yet | same listing — only `artifacts.ngs.bz` + two `thclaws.ngs.bz` apps |
| `r2-artifacts.ngs.bz` has **no DNS record** → hostname is free to use | `dig +short r2-artifacts.ngs.bz` → empty |
| `artifacts.ngs.bz` is proxied through Cloudflare (104.21.x / 172.67.x) and still serves legacy SFTP artifacts | `dig` + an artifact published 2026-10-31 |
| API token cannot read R2 custom domains (`10015 No route matches this url`) → domain state must be checked in the dashboard | `GET /r2/buckets/pundai/domains` |
| S3 key scope on `pundai` (PutObject/ListBucket) is **unproven** | credentials never used by the agent; proven only by Stage C |

---

## 2. Why not Option A (bind `pundai` to `artifacts.ngs.bz`)

One hostname serves one origin. Rebinding `artifacts.ngs.bz` to R2 would stop every legacy artifact URL already shared — no split without Workers. Rejected by both review lanes.

---

## 3. Stage B — owner-side Cloudflare provisioning (this order, fail-closed)

1. **R2 → `pundai` → Settings** — confirm `r2.dev` public access is **disabled** and no custom domain is already attached.
2. **Zero Trust → Access → Applications → Add (Self-hosted)**
   - Name: `Artifacts R2 Private (v1)`
   - Domain: `r2-artifacts.ngs.bz`, Path: `/*/private/*`
   - Policy: mirror the existing `Artifacts all tools private` app (same IdP, same allow list, same session duration)
   - Save **before** step 4.
3. **Zone `ngs.bz` → Rules → Transform Rules → Rewrite URL**
   - Name: `R2 Artifacts Trailing Slash`
   - When: `ends_with(http.request.uri.path, "/")`
   - Then: Rewrite path → Dynamic → `concat(http.request.uri.path, "index.html")`
4. **R2 → `pundai` → Settings → Custom Domains → Connect Domain** → `r2-artifacts.ngs.bz`; wait for **Active**.

---

## 4. Stage C — rehearsal in a throwaway HOME (owner terminal)

Validates credentials, bucket, and argument handling without touching the live profile. Secret flows on stdin only.

```bash
source ~/.zshrc
REHEARSE_HOME=$(mktemp -d)
printf '%s\n' "$CLOUDFLARE_SECRET_ACCESS_KEY" | env HOME="$REHEARSE_HOME" \
  bash /Users/ngs/agent-skills/plugins/artifact-sftp/skills/artifact-sftp/scripts/setup.sh \
  --driver s3 --s3-endpoint "$CLOUDFLARE_API_ENDPOINT" --s3-bucket pundai \
  --s3-key-id "$CLOUDFLARE_S3_ACCESS_KEY_ID" --s3-secret - --s3-region auto \
  --url "https://r2-artifacts.ngs.bz" --tool openclaw --profile-version 2
env HOME="$REHEARSE_HOME" bash /Users/ngs/agent-skills/plugins/artifact-sftp/skills/artifact-sftp/scripts/setup.sh --status
rm -rf "$REHEARSE_HOME"
```

Expect: `storage driver: s3`, `profile version: v1 project namespace`, `READY`. If the key lacks bucket permissions, `--status` still passes locally — the real proof is Stage D's first `--ping`.

Optional stronger rehearsal (needs a throwaway config that points at the real bucket):

```bash
env HOME="$REHEARSE_HOME" PATH="/Users/ngs/agent-skills/plugins/artifact-sftp/.venv/bin:$PATH" \
  ARTIFACT_SFTP_MCP_CALL=1 ARTIFACT_SFTP_PYTHON=/Users/ngs/agent-skills/plugins/artifact-sftp/.venv/bin/python \
  bash /Users/ngs/agent-skills/plugins/artifact-sftp/skills/artifact-sftp/scripts/publish.sh --ping
```

Exit 0 = endpoint + credentials + listing permission proven before the live switch.

---

## 5. Stage D — switch the live profile

```bash
source ~/.zshrc
printf '%s\n' "$CLOUDFLARE_SECRET_ACCESS_KEY" | \
  bash /Users/ngs/agent-skills/plugins/artifact-sftp/skills/artifact-sftp/scripts/setup.sh \
  --driver s3 --s3-endpoint "$CLOUDFLARE_API_ENDPOINT" --s3-bucket pundai \
  --s3-key-id "$CLOUDFLARE_S3_ACCESS_KEY_ID" --s3-secret - --s3-region auto \
  --url "https://r2-artifacts.ngs.bz" --tool openclaw --profile-version 2 --replace
```

`--replace` writes `config.bak-<stamp>.XXXXXX` (and the same for `known_hosts`) beside the live files before overwriting.

---

## 6. Post-switch verification

**Agent can verify (MCP only):**
- `artifact_sftp.setup(verify_connection=true)` → must report `storage driver: s3` and `profile version: v1 project namespace`, remote preflight `verified`.
- A private canary publish → the v1 pre-flight anonymous probe must show the R2 host is Access-gated; `exit 7` = exposed (stop), `exit 8` = inconclusive (stop) — both mean "nothing uploaded".

**Owner must verify (dashboard, not provable by MCP):**
- `r2.dev` disabled; custom domain **Active**; Access app covers `r2-artifacts.ngs.bz/*/private/*`; Transform Rule deployed; `artifacts.ngs.bz` DNS untouched.

---

## 7. Rollback

Legacy serving is untouched by design (legacy host keeps its own origin). To return this machine to SFTP:

```bash
ls ~/.config/artifact-sftp/config.bak-*
cp ~/.config/artifact-sftp/config.bak-<stamp>.XXXXXX ~/.config/artifact-sftp/config
chmod 600 ~/.config/artifact-sftp/config
```

Then `artifact_sftp.setup` reports `auth: password` / `profile: legacy` again. Legacy artifacts on `artifacts.ngs.bz` never moved, so they keep resolving throughout.

---

## 8. Open owner decisions

- Access policy audience for the new app (mirror the existing one, or tighten to a named group).
- Whether to keep `openclaw` as `DEFAULT_TOOL` (provenance only in v1).
- Whether legacy and R2 will run side by side indefinitely (supported) or whether a later explicit migration for old URLs is wanted (not built, not promised).
