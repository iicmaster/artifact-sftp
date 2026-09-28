# ADR 0001: S3-Compatible Storage Driver (Cloudflare R2 + Custom Domain + Cloudflare Access)

- **Status:** Accepted / Implemented
- **Date:** 2026-08-27 (Updated: 2026-09-01)
- **Deciders:** Winston (System Architect), Mary (Business Analyst), Amelia (Senior Dev), John (PM), Sally (UX), Master

---

## 1. Context & Problem Statement

`artifact-sftp` historically required an active SSH/SFTP server to publish HTML artifacts. While SFTP provides POSIX atomic renaming and allows Nginx/Apache to enforce Cloudflare Zero Trust or Basic Auth on `/private/*`, many developers and teams prefer serverless object storage (such as Cloudflare R2, AWS S3, or MinIO) with zero VPS maintenance and $0 egress bandwidth costs.

However, standard object storage lacks built-in authentication layers for selective path protection. We need an architecture that supports S3/R2 storage while preserving:
1. **Clean Semantic Trailing-Slash URLs:** `https://artifacts.example.com/<tool>/<visibility>/<slug>/`
2. **Fail-Closed Private Access Protection:** Private artifacts must be gated behind authentication (e.g. Cloudflare Zero Trust Access OTP/SSO) and pass anonymous probe tests (302/401/403).
3. **Local Custody & Versioning Parity:** Maintain local archives and immutable timestamped snapshots under `docs/artifacts/`.
4. **Zero External Dependencies:** Use standard Python libraries (`urllib.request`, `hmac`, `hashlib`, `xml.etree`) with AWS Signature Version 4 (SigV4) to avoid heavy third-party packages (e.g. Boto3).

---

## 2. Decision: Option 1 (Cloudflare R2 + Custom Domain + Cloudflare Access)

We select **Cloudflare R2 + Custom Domain + Cloudflare Zero Trust Access** as our primary S3 driver architecture pattern.

```text
                 [AI Agent Client]
                         │
         (MCP Tool: artifact_sftp.publish)
                         ▼
           [Local Artifact SFTP MCP Server]
                         │
         (S3 Driver: Pure Python SigV4 stdlib)
                         ▼
           [Cloudflare R2 Bucket (Private)]
                         ▲
                         │
           [Custom Domain / Cloudflare CDN]
            (e.g. artifacts.mycompany.com)
            ├── /public/*  ──> Anonymous Allowed (Cache-Control: public, max-age=300)
            └── /private/* ──> Cloudflare Access Gate (Cache-Control: private, no-cache)
```

---

## 3. Strict Security & Provisioning Sequence (Fail-Closed)

To prevent an accidental public exposure window during initial onboarding, the provisioning sequence MUST strictly follow this order:

1. **Step 1 — Create Private R2 Bucket:** Create bucket (e.g. `artifacts`). Ensure `r2.dev` public bucket URL is **DISABLED** (to prevent bypassing Access).
2. **Step 2 — Create Scoped API Token:** Create an R2 API Token with **Object Read & Write** permissions scoped exclusively to the target bucket (never Admin Read/Write).
3. **Step 3 — Create Cloudflare Access Application FIRST:** Configure Zero Trust Access Application on domain `artifacts.mycompany.com` for path `*/private/*` with Email/Domain OTP rules.
4. **Step 4 — Connect Custom Domain to R2 Bucket:** Attach `artifacts.mycompany.com` in Cloudflare R2 settings. Because Access was configured in Step 3, `/private/*` is protected immediately upon domain attachment.
5. **Step 5 — Configure Cloudflare Transform Rule (URL Rewrite):**
   Cloudflare R2 custom domains serve exact object keys. To allow clean URLs ending in `/`, create a URL Rewrite Transform Rule in Cloudflare Dashboard:
   - **Rule Name:** `R2 Trailing Slash Index Rewrite`
   - **When:** `ends_with(http.request.uri.path, "/")`
   - **Action:** `Rewrite Path -> Dynamic -> concat(http.request.uri.path, "index.html")`
6. **Step 6 — Configure Local Profile:** Add credentials to `~/.config/artifact-sftp/config` (`STORAGE_DRIVER=s3`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `PUBLIC_BASE_URL`).

---

## 4. Key Implementation Invariants

- **Zero Third-Party Dependencies:** `s3_helper.py` implements AWS SigV4 using Python's built-in `urllib`, `hmac`, and `hashlib`.
- **Cache-Control per Visibility:**
  - `private` artifacts: `Cache-Control: private, no-cache` (never `public`).
  - `public` index: `Cache-Control: public, max-age=300`.
  - `public` snapshots: `Cache-Control: public, max-age=31536000, immutable`.
- **Key Layout Parity:**
  - Current Index: `<tool>/<vis>/<slug>/index.html`
  - Versioned Snapshot: `<tool>/<vis>/<slug>/<slug>--<v>--<ts>.html`
- **Pagination & Safety Limit:**
  - `list_objects_v2_paged` iterates over `IsTruncated` and `NextContinuationToken` for complete delete/version enumerations.
  - 5 MiB object size limit enforced before upload and after fetch.
