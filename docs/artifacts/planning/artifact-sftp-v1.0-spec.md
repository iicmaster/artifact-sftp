# Artifact SFTP v1.0 — Product & Technical Specification

- **สถานะ:** Implemented — Phase A–D ตามสเปกนี้ถูก implement บน branch `feat/v1-project-namespace` (ADR 0002, parsers, v1 layout, pre-flight gate, workspace binding, wizard/setup markers, tests) และเผยแพร่เป็น release **1.0.0**. งานที่เหลือเป็น *operational*: พิสูจน์ Access wildcard บน tenant จริง (Phase C gate ทำงานผ่าน pre-flight แล้ว) และตรวจ demand ของ migration tool จากการใช้งานจริง
- **วันที่:** 2026-10-30 (แก้ครั้งที่ 3 หลัง review ข้าม vendor + Master ยืนยัน `publict` เป็น typo)
- **เจ้าของการตัดสิน:** Master (ยืนยันความต้องการทางธุรกิจ; มอบอำนาจตัดสินทางเทคนิคให้วง)
- **ความต้องการทางธุรกิจที่ Master ระบุ:** URL แบบ `/{project}/{private|public}/{name}/` (project-first), Cloudflare เป็นค่าเริ่มต้นของการตั้งค่าใหม่, private/public แยกชัด, publishing ผ่าน MCP เหมือนเดิม
- **เอกสารอ้างอิง:** ADR 0001 ยังผูก driver ที่ ship แล้ว; implementation ต้องมี ADR v1.0 ตามสเปกนี้

> **ตัดสินแล้ว (Master, 2026-10-30):** `publict` คือ typo ของ `public`. Canonical visibility คือ `private|public` เท่านั้น — runtime reject ค่าอื่นด้วย `ERR_INVALID_VISIBILITY` (แนะนำคำที่ถูกได้ แต่ห้าม normalize แล้ว publish).

## 1. สรุปผู้บริหาร

v1.0 เปลี่ยน canonical identity เป็น:

```text
https://<owner-configured-domain>/{project}/{visibility}/{slug}/
```

- **Route project-first ตามความต้องการทางธุรกิจ** (ตัดสินแล้ว — ไม่สลับเป็น visibility-first โดยปริยาย)
- **Cloudflare R2 = preselected recipe ของ v1 profile ใหม่** (ตัดสินแล้ว — เป็น default ของการ *เริ่ม setup ใหม่* ไม่ใช่ zero-config storage; existing profile ไม่ถูกแตะ)
- MCP input คง `slug` + `tool` เดิม; เพิ่ม `project` (optional ต่อ call, resolve จาก workspace binding)
- Legacy (`/{tool}/…`) อ่านได้ต่อบน profile เดิม; การเขียนแบบ v1 เกิดเฉพาะเมื่อ owner เปิด v1 profile อย่างชัดเจน

**เงื่อนไขก่อน implementation:** ตาราง decisions ใน §13 ปิดแล้วทั้งหมด (ด้านล่าง); เหลือ *งานตรวจสอบเชิงเทคนิค* 2 ชิ้นที่ทำตอน implementation ไม่ใช่คำถามรอ Master: (ก) พิสูจน์ Access wildcard coverage บน tenant จริง (ข) ยืนยันว่าไม่มีความต้องการ migration tool จากการใช้งานจริง

## 2. ข้อเท็จจริงระบบปัจจุบัน (verified ใน repo)

- `publish` รับ `project_path, source_path, slug, tool, visibility`; `tool ∈ {codex, openclaw, claude}`; `visibility ∈ {private, public}`; `project_path` เป็น working dir + local archive boundary ไม่อยู่ใน URL
- URL/`docs/artifacts` layout ปัจจุบัน: `{tool}/{visibility}/{slug}/…`
- Config ไม่มี `STORAGE_DRIVER` = SFTP (legacy default คงไว้); R2 มี S3-compatible driver แล้ว; `setup` read-only, ของ owner provision เอง
- ADR 0001 invariants: ปิด `r2.dev`, token scoped ต่อ bucket, Access ก่อน bind domain, trailing-slash rewrite, private fail-closed, snapshot immutable + local archive
- ทำงานได้โดยไม่ต้องมี Git; artifact เป็น static HTML บน origin เดียวกัน

## 3. Goals

1. Canonical URL `/{project}/{private|public}/{slug}/`; project เป็น logical namespace แยกจาก filesystem path
2. v1 profile ใหม่ preselect Cloudflare R2 อย่างโปร่งใส; ไม่ฝัง credential/domain; ไม่ fallback เมื่อ setup ไม่ครบ
3. คง private-by-default, `confirm_public`, custody guard, immutable snapshots, bounded I/O, local archive
4. Legacy อ่านได้ต่อ; ไม่ migrate/rewrite ข้อมูลเงียบๆ
5. SFTP และ S3-compatible อื่นยังเลือกได้; ไม่บังคับเงื่อนไข Cloudflare กับ provider อื่น
6. รายงานสถานะแยกชัด: config / storage reachable / object read-back / policy verified

## 4. Non-goals

- Provision bucket/token/domain/DNS/Access app อัตโนมัติ
- ใช้ URL segment เป็น authorization
- อ้าง tenant isolation ระหว่าง project บน origin เดียว
- ย้าย/ลบ remote objects อัตโนมัติใน publish path
- Derive project จาก Git/path
- รับ credentials ผ่าน MCP arguments

## 5. Domain model

### 5.1 Project — ตัดสินแล้ว

`project` = **owner-assigned content namespace ภายใน publishing destination/profile หนึ่ง**. ไม่ใช่ tenant, membership หรือ authorization claim; สตริงเดียวกัน/path เดียวกันไม่พิสูจน์ custody.

**แหล่งค่า (resolution order ตัดสินแล้ว):**
1. `project` argument ใน MCP call (ถ้ามี)
2. Workspace binding `.artifact-sftp.json` ที่ project root: `{"project": "<id>"}` (ไฟล์ไม่มี secret, commit ได้)
3. ไม่มีทั้งคู่ → error `PROJECT_ID_REQUIRED` ก่อน write ใดๆ (พร้อมแนะนำการตั้ง config)

- Argument ขัด config → `PROJECT_ID_CONFLICT`, ห้ามเดา/เลือกเงียบๆ
- ห้าม derive จาก `project_path`/Git remote/basename
- Grammar: `^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$` (1–63, lowercase, เริ่ม/จบ alphanumeric), reject slash/dot-segment/percent-encoding/whitespace/Unicode ambiguity/**reserved roots** (§5.4)

### 5.2 Slug และ tool — ตัดสินแล้ว

- **คงชื่อ argument `slug`** (ไม่ rename เป็น `name`; `{name}` ใช้เรียกตำแหน่งใน URL เท่านั้น) — ลด caller breakage, ตรง requirement "ระบบเดิมยังทำงาน"
- **คง `tool` เป็น provenance metadata** — เก็บใน snapshot/archive metadata และ `list` ผลลัพธ์; ไม่อยู่ใน URL/key identity; `tool` ที่ caller อ้างไม่ให้สิทธิ์ overwrite
- Identity = `(profile/destination, project, visibility, slug)`; ชนกันข้าม tool = structured conflict (`IDENTITY_CONFLICT`) รายงานทั้งสองแหล่ง ห้ามเขียนทับ; `force` ไม่ข้าม custody

### 5.3 URL / object key / local archive

```text
URL:    https://<PUBLIC_BASE_URL>/{project}/{visibility}/{slug}/
Keys:   {project}/{visibility}/{slug}/index.html
        {project}/{visibility}/{slug}/{slug}--{version}--{UTC_TIMESTAMP}.html
Local:  docs/artifacts/{project}/{visibility}/{slug}/… (โครงเดียวกับ keys)
```

Trailing `/` → rewrite ต่อ `index.html`; snapshot ก่อน live index เสมอ (object storage); ชื่อไฟล์ snapshot ตาม contract เดิม

### 5.4 Reserved legacy roots — ตัดสินแล้ว

ขณะ legacy และ v1 อยู่ coexist บน destination เดียวกัน: **`codex`, `openclaw`, `claude` เป็น reserved project IDs** — v1 ห้ามใช้เป็นชื่อ project ใหม่ (error `RESERVED_PROJECT_ID` พร้อมแนะนำชื่ออื่น). เหตุผล: `/codex/private/x/` ตีความได้สองแบบจาก bytes เดียวกัน; reserving รากถูกสุดในสามทาง (แยก origin/prefix ทางกายภาพ = แพงกว่า; เดา layout = ห้าม). ถ้า destination ถูกแยกกายภาพจริง (bucket/origin ใหม่ล้วน) ข้อ reserve นี้คลายเองได้ตาม profile

## 6. Visibility, Access และ same-origin — ตัดสินแล้ว + เงื่อนไขพิสูจน์

- `private` default; ต้องมี Access policy ที่พิสูจน์ครอบคลุมแล้ว; `read` ไม่ fetch private URL แบบ anonymous
- `public` = anonymous ผ่าน custom domain โดยเจตนาของ owner + `confirm_public=true` เสมอ
- `publict`/ค่าอื่น → `ERR_INVALID_VISIBILITY` (สะกดผิดถูกยืนยันแล้ว; runtime ยัง reject เพราะ enum ต้อง strict)
- Bucket private, `r2.dev` ปิด

**Access recipe สำหรับ project-first (ตัดสินแล้ว):** เป้าหมายคือ **Access application เดียว path `/*/private/*`** ครอบทุก project ตลอดอายุ ไม่ต้องแตะ dashboard ต่อ project. ข้อจำกัดความรู้: wildcard multi-segment บน tenant/plan จริง **ยังไม่ถูกพิสูจน์** (ทั้งสอง reviewer ปฏิเสธอ้างโดยไม่มีหลักฐาน) จึงกำหนดเป็นงานพิสูจน์ตอน provisioning:

1. Owner ตั้ง Access app ตาม recipe; provisioning checklist ตรวจ effective coverage: private index, snapshot, มี/ไม่มี trailing slash, redirect ของ edge, bypass precedence
2. **Pre-flight gate:** ก่อน private publish ครั้งแรกของแต่ละ `{project}` — anonymous HEAD ต้องได้ `302/401/403` (Access response ที่รู้จัก); ได้ `200` = `CRITICAL_SECURITY_FAILURE`, block publish, ไม่มี success URL
3. **Post-publish gate:** anonymous probe ซ้ำหลัง publish ทุกครั้ง (bounded, ไม่คืน body); ไม่แน่ใจ = exit 8 semantics เดิม (inconclusive, fail-closed)
4. ถ้าพิสูจน์แล้ว wildcard ไม่รองรับบน tenant: recipe สำรอง = domain-wide Access + bypass rules ที่ narrow สำหรับ `/*/public/*` — ต้องผ่าน gate เดียวกัน และหาก owner ต้องการจริงจะเสนอ visibility-first เป็น **alternative profile ที่ต้องเลือกแบบ explicit** (ไม่ใช่ default)

**Same-origin trust (ตัดสินแล้ว):** artifact ทั้งหมดบน origin เดียว = **trust domain เดียว**. บริบทธุรกิจ: publisher คือ owner เดียว, HTML เป็นของ owner เอง → ยอมรับ shared trust domain, ไม่ทำ per-project origin isolation ใน v1. เงื่อนไขที่ต้องประกาศใน docs: **ห้าม publish HTML ของบุคคลที่สามที่ไม่ได้ตรวจ** ลง origin เดียวกับ private artifact; บังคับผ่าน `artifact-audit` gate + เพิ่ม audit rule "untrusted third-party HTML on shared origin" เป็น blocker. ถ้าวันหนึ่งต้องรองรับ mutually untrusted publishers ต้องออกแบบ origin/sandbox แยกก่อน (future scope, ไม่ block v1)

## 7. Storage default และ readiness — ตัดสินแล้ว

### 7.1 Fresh v1 profile

- เฉพาะ **explicit owner action** ("เริ่ม v1 profile") เท่านั้นที่สร้าง profile ใหม่; UI/wizard **preselect Cloudflare R2** (`STORAGE_DRIVER=s3`, provider `cloudflare-r2`) โดยแสดงผลชัดว่าเป็น "recommended & preselected — ต้อง provisioning ก่อนใช้"
- Marker ของ v1 profile: ฟิลด์ versioned ใน config (เช่น `PROFILE_VERSION=2` + `PROFILE_PROVIDER=cloudflare-r2`) — การ upgrade package หรือ config ที่ไม่มี driver **ไม่ใช่**การเริ่ม v1; ยังเป็น SFTP ตามเดิม
- Setup wizard เขียน config (owner รันเอง/terminal-owned secrets ตามเดิม); `artifact_sftp.setup` (MCP) read-only รายงานสถานะ + ชื่อ field ที่ขาด ห้าม echo secret
- **Readiness state machine (บังคับใช้จริงใน status/publish):** `UNCONFIGURED → CONFIG_INCOMPLETE → CONFIGURED_UNVERIFIED → STORAGE_REACHABLE → PRIVATE_POLICY_VERIFIED → READY` — publish private ต้องถึง `PRIVATE_POLICY_VERIFIED`; publish public ต้อง `STORAGE_REACHABLE` + `confirm_public`; ไม่มี fallback ข้าม backend ทุกกรณี
- ไม่มี default domain/bucket ใดๆ ฝังในโค้ด (G10 เดิมห้ามกลับ)

### 7.2 Existing installs และ alternate drivers

- Existing profile คง backend/layout/URL เดิมทุกอย่าง; ไม่มี auto-migration จากการ upgrade
- SFTP/MinIO/AWS: explicit เสมอ; ไม่บังคับ Access/`r2.dev`/`S3_REGION=auto` กับ non-R2

## 8. API — ตัดสินแล้ว

```text
publish:   project_path, source_path, slug, tool?, project?, visibility="private",
           dry_run, confirm, confirm_public
unpublish: project_path, slug, tool?, project?, visibility="private",
           dry_run, confirm, confirm_public
read:      project_path, reference, …  (รับ v1 URL, legacy URL, read-back path, archive path)
list:      เพิ่ม field project; คง tool/visibility filters; แยก namespace ชัด
```

- `project` optional ใน schema — resolve ตาม §5.1; **ไม่บังคับทุก call** เพื่อไม่ทำให้ agent/skill เดิมพังทันที แต่ v1-mode publish **ต้อง resolve ได้** ไม่งั้น `PROJECT_ID_REQUIRED`
- Legacy profile (ไม่มี v1 marker): contract/behavior เดิม 100% รวม `tool` ใน path — old callers ไม่แตก
- `read` reference: constraint ที่ configured origin allowlist; ห้ามส่ง credentials ไป host อื่น/redirect; legacy URL resolve ได้เฉพาะเมื่อ profile bound กับ destination นั้น
- `unpublish` deletion set ระบุชัดในผลลัพธ์: remote index + snapshots ที่โดนลบ, local archive **retain** (คงเดิม), partial failure → error พร้อมสิ่งที่ยังเหลือ; ห้ามรายงาน `unpublished` ถ้า index ยังอยู่

## 9. Legacy coexistence & migration lifecycle — ตัดสินแล้ว

- **States:** `LEGACY_ACTIVE` (เขียน/อ่าน layout เดิม) → `V1_UNCONFIGURED` (owner เริ่ม v1 profile, R2 preselected, publish block จน READY) → `V1_ACTIVE` (เขียน keys ใหม่เท่านั้น) ; `TRANSITIONAL` read (v1 → legacy) ใช้ได้เฉพาะ destination เดียวกัน + confirmed-absence เท่านั้น
- Legacy reads บน v1 fresh bucket: รายงาน "ไม่พบ" ตรงๆ — ไม่มีข้อมูลเก่าใน bucket ใหม่โดยอัตโนมัติ (แยกเรื่อง URL parser ออกจาก data migration ให้ชัด)
- **Migration tool: ไม่ทำใน v1.0** — จัดเป็นงานตรวจสอบ demand จากการใช้งานจริง; ถ้าต้องทำ ต้องเป็น explicit dry-run → owner approve → copy → verify bytes+policy → rollback plan (ตามที่ reviewers ทั้งสองฝั่งกำหนด)
- ระยะรองรับ legacy read: **คง parser ไว้ยาว** (ต้นทุนต่ำ อยู่ใน read resolver อยู่แล้ว); ประกาศ deprecation เมื่อมีข้อมูลใช้จริง ไม่ fix วันตัดตอนนี้

## 10. Security & operational invariants (ครบชุดเดิม + เพิ่ม)

1. `exit 1` = confirmed remote ENOENT เท่านั้น (สัญญา v0.22.5)
2. ห้าม overwrite โดยไม่มี custody proof ผูกกับ destination; `force` ไม่ข้าม version-list failure
3. Project string ไม่ใช่ authorization; ไม่อ้าง tenant isolation บน shared origin
4. Private protection เป็น property ที่พิสูจน์แยก — config ครบ/read-back ผ่าน ไม่ใช่หลักฐาน
5. `r2.dev` ปิด; least-privilege token; เอกสารระบุ listing permission ที่จำเป็น
6. **`artifact-audit` pre-flight บังคับก่อน publish/groom** — critical blocker ข้ามไม่ได้ด้วย confirm/dry-run/force; เพิ่ม rule: untrusted third-party HTML บน shared origin = blocker
7. Validate project/slug/URL/key/archive/redirect: traversal, encoded separator, case, Unicode, reserved roots, ขีดจำกัด byte ของ provider
8. Bound size/read/pagination/timeout/retry; failure ไม่กลายเป็น empty-success หรือ version 1
9. รายงานแยก: local archive saved / remote read-back / domain serving / policy verified — ไม่มี `verified` รวมๆ
10. ไม่มี secret ใน MCP args/URL/log/spec/example/artifact

## 11. Rollout & acceptance (แผน implement ภายหลัง)

- **Phase A — contract freeze:** ADR v1.0 จากสเปกนี้; parsers/validators (ใหม่+เก่า) + tests ก่อนแตะ write path
- **Phase B — project resolution & config:** `.artifact-sftp.json` reader, conflict/missing errors, reserved roots, strict visibility enum, v1 profile marker; ไม่มี remote migration
- **Phase C — Access/storage proof:** provisioning checklist + pre-flight/post-publish anonymous probes บน tenant จริง (ไม่ใช้ private เนื้อหาจริงเป็น probe ก่อน gate); ตรวจ wildcard `/*/private/*`; ไม่ผ่าน → block + รายงาน
- **Phase D — v1 publish/read/unpublish:** keys/local layout ใหม่, legacy profile คงเดิม, failure injection ทุก stage, legacy-read-bound-to-destination, audit gate ใน acceptance

Acceptance tests สืบทอดรายการเดิม (§11 ฉบับก่อน) + เพิ่ม: `PROJECT_ID_REQUIRED/CONFLICT/RESERVED`, `ERR_INVALID_VISIBILITY` (รวม `publict`), Access wildcard coverage จริง, anonymous probe fail-closed, unpublish partial-failure reporting, audit-blocker behavior

## 12. ที่มาของการตัดสิน (advisor synthesis)

- Review lanes (receipt-verified): Codex `gpt-6.1-sol[ultra]` (`e0036962`), Gemini `gemini-3.8-flash-high` (`e2acc267`) — brief เดียวกัน, roster grumble-room, read-only
- **ข้อที่สอง vendor ชี้ตรงกัน (รับทั้งหมด):** ห้าม normalize `publict`; "Cloudflare default" = preselected recipe จนกว่า provisioning/readiness จริง; project ≠ tenant/auth; การตัด tool ออกทำให้เกิด collision + path alias จริง; `project_path` ใช้เป็น project ID ไม่ได้; legacy read ≠ data migration; path label ไม่ใช่ policy; ต้องมี audit gate + operation outcomes ชัด
- **ข้อที่เห็นต่าง (วงตัดสินแล้วตามเหตุผลที่บันทึก):** route → คง project-first ตามธุรกิจ + พิสูจน์ wildcard (ไม่สลับ visibility-first โดยดีฟอลต์); project source → workspace binding + per-call override (ยอมรับข้อเสีย "เพิ่ม config file" เพื่อลด friction/name-drift ที่ Sally/Amelia ชี้); `slug` → คงชื่อเดิม (เสียง Sally/Amelia/John ฝั่ง compatibility ชนะข้อสวยงามของการ rename)
- ข้อจำกัดหลักฐานที่คงไว้: ทั้งสอง lane ไม่ได้ตรวจ Cloudflare tenant/plan/HTML จริง — จึงกลายเป็นงานพิสูจน์ใน Phase C ไม่ใช่ข้อสรุปในสเปก

## 13. Decision ledger (ปิดครบ 2026-10-30)

| # | ประเด็น | คำตัดสิน | อำนาจ |
|---|---|---|---|
| 1 | สะกด `publict` | **typo → canonical `public`; runtime reject ค่าอื่น** | Master (ธุรกิจ) |
| 2 | ลำดับ route | **project-first คงตามคำขอ** + Access wildcard ต้องพิสูจน์ (Phase C); visibility-first เป็น alternative profile เท่านั้น | วง (delegated) — ยึดธุรกิจ |
| 3 | project semantics | **content grouping** (ไม่ใช่ tenant); resolution: arg > `.artifact-sftp.json` > `PROJECT_ID_REQUIRED`; conflict → error | วง (delegated) |
| 4 | legacy roots | **reserve `codex\|openclaw\|claude`** ขณะ coexist บน destination เดียวกัน | วง (delegated) |
| 5 | API shape | **คง `slug` + `tool`** (provenance); ไม่ rename | วง (delegated) |
| 6 | trust boundary | **single trust domain** ประกาศชัด + audit rule ห้าม untrusted HTML; origin isolation เป็น future scope | วง (delegated) |
| 7 | legacy window / migration | read parser คงไว้ยาว; **ไม่มี migration tool ใน v1.0**; ตรวจ demand ก่อน | วง (delegated) |
| 8 | ความหมาย "Cloudflare default" | **preselected recipe ของ explicit v1 profile** + readiness state machine บังคับ | วง (delegated) |

---

**สถานะ:** สเปก RC — decisions ปิดครบตามการมอบอำนาจ. ยังไม่มี implementation/config/PR/release; ขั้นถัดไปเมื่อ Master สั่ง: แตกงาน implement ตาม Phase A–D (เริ่มที่ ADR v1.0 + parsers)
