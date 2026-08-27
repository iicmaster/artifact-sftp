# ADR 0001: S3-Compatible Storage Driver (Cloudflare R2 + Custom Domain + Cloudflare Access)

- **Status:** Proposed / Validation Required (Spike Phase)
- **Date:** 2026-08-27
- **Deciders:** Winston (System Architect), Mary (Business Analyst), Amelia (Senior Dev), John (PM), Sally (UX), Master

---

## 1. Context & Problem Statement

`artifact-sftp` currently requires an active SSH/SFTP server to publish HTML artifacts. While SFTP provides POSIX atomic renaming and allows Nginx/Apache to enforce Cloudflare Zero Trust or Basic Auth on `/private/*`, many developers and teams prefer serverless object storage (such as Cloudflare R2, AWS S3, or MinIO) with zero VPS maintenance and $0 egress bandwidth costs.

However, standard object storage lacks built-in authentication layers for selective path protection. We need an architecture that supports S3/R2 storage while preserving:
1. **Clean Semantic Trailing-Slash URLs:** `https://artifacts.example.com/<tool>/<visibility>/<slug>/`
2. **Fail-Closed Private Access Protection:** Private artifacts must be gated behind authentication (e.g. Cloudflare Zero Trust Access OTP/SSO) and pass anonymous probe tests (302/401/403).
3. **Local Custody & Versioning Parity:** Maintain local archives and immutable timestamped snapshots under `docs/artifacts/`.

---

## 2. Decision: Option 1 (Cloudflare R2 + Custom Domain + Cloudflare Access)

We select **Cloudflare R2 + Custom Domain + Cloudflare Zero Trust Access** as our primary S3 driver architecture pattern.

```text
               [AI Agent / MCP Client]
                          │
          (S3 PUT API: Boto3 / S3 REST Client)
                          ▼
            [Cloudflare R2 Bucket (Private)]
                          ▲
                          │
            [Custom Domain / Cloudflare CDN]
             (e.g. artifacts.mycompany.com)
             ├── /public/*  ──> Anonymous Allowed
             └── /private/* ──> Cloudflare Access Gate (OTP/SSO Login)
```

---

## 3. Strict Security & Provisioning Sequence (Fail-Closed)

To prevent an accidental public exposure window during initial onboarding, the provisioning sequence MUST strictly follow this order:

1. **Step 1 — Create Private R2 Bucket:** Create bucket (e.g. `artifacts`). Ensure `r2.dev` public bucket URL is **DISABLED** (to prevent bypassing Access).
2. **Step 2 — Create Scoped API Token:** Create an R2 API Token with **Object Read & Write** permissions scoped exclusively to the target bucket (never Admin Read/Write).
3. **Step 3 — Create Cloudflare Access Application FIRST:** Configure Zero Trust Access Application on domain `artifacts.mycompany.com` for path `*/private/*` with Email/Domain OTP rules.
4. **Step 4 — Connect Custom Domain to R2 Bucket:** Attach `artifacts.mycompany.com` in Cloudflare R2 settings. Because Access was configured in Step 3, `/private/*` is protected immediately upon domain attachment.
5. **Step 5 — Configure Local Plugin Profile:** Add credentials to `~/.config/artifact-sftp/config` (`STORAGE_DRIVER=s3`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `PUBLIC_BASE_URL`).

---

## 4. Key Proof Requirements for Spike Phase

Before merging full S3/R2 driver implementation into the MCP server:
- **Object Key Layout:** Store both current index (`/<tool>/<vis>/<slug>/index.html`) and versioned snapshot (`/<tool>/<vis>/<slug>/<slug>--<v>--<ts>.html`).
- **Trailing-Slash URL Resolution:** Verify Cloudflare Custom Domain on R2 correctly serves `index.html` on directory requests (`https://domain/<tool>/<vis>/<slug>/`). If required, document Cloudflare Transform Rule for index rewriting.
- **Privacy Probe & Hash Match:** Verify anonymous probe returns 302/401/403 and authenticated probe verifies SHA-256 integrity match.
