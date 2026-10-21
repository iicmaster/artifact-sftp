# แผนงานสถาปัตยกรรม: S3-Compatible Driver (Cloudflare R2 + Custom Domain + Access)

**เอกสารบันทึกแผน:** `docs/plans/s3-cloudflare-r2-plan.md` (ย้ายเข้า git เมื่อ 2026-10-21; เดิมอยู่ที่ `_bmad-output/planning-artifacts/` ซึ่งอยู่ใน `.gitignore` และจึงหายไปกับการ clone ใหม่)
**สถานะ:** ✅ **ดำเนินการเสร็จสิ้น (Implemented)** — 27 ส.ค. 2026 อนุมัติแผน, ส่งมอบใน release **v0.22.0** (28 ก.ย. 2026)
**เอกสารตัดสินใจ:** [`docs/adr/0001-s3-cloudflare-r2-driver.md`](../adr/0001-s3-cloudflare-r2-driver.md) — ADR เป็นเจ้าของข้อกำหนดสุดท้าย (fail-closed provisioning sequence, invariants)
**รายงาน gap ระหว่างแผนกับโค้ดจริง:** [`docs/plans/s3-cloudflare-r2-gap-report.md`](s3-cloudflare-r2-gap-report.md)
**PR:** #31 (squash-merge เป็น `0611698`) + #34 (แก้ fail-open ของ S3 overwrite guard)

> **หมายเหตุ:** เอกสารฉบับนี้คงข้อความแผนเดิมไว้เพื่อการตรวจสอบย้อนหลัง ยกเว้นสถานะด้านบนและหมายเหตุที่ระบุไว้ชัดเจน — เมื่อแผนกับ ADR ขัดกัน **ADR ชนะเสมอ**

---

## 0. ผลการดำเนินการ (Implementation Outcome)

| ข้อกำหนดในแผน | สถานะ | หลักฐาน |
|---|---|---|
| §2 สถาปัตยกรรม Option 1 (R2 + Custom Domain + Zero Trust Access) | ✅ | `docs/adr/0001-s3-cloudflare-r2-driver.md` §2 |
| §2 URL parity `https://host/<tool>/<visibility>/<slug>/` | ✅ | `publish.sh` (สร้าง URL) + `service.py` (ตรวจ shape) — เหมือนกันทั้งสอง driver |
| §2 Security probe compatibility (302/401/403 = ปลอดภัย) | ✅ | probe เป็น driver-agnostic — ทำงานเหมือนกันทั้ง SFTP และ S3 |
| §3.1 Config keys ทั้งหมด | ✅ | `setup.sh` เขียน/อ่านครบ รวม `CF_ACCESS_*` (optional) |
| §3.2 Zero third-party dependency (SigV4 ด้วย stdlib) | ✅ | `skills/artifact-sftp/scripts/s3_helper.py` — ไม่มี boto3; ทดสอบด้วย official AWS SigV4 vectors |
| §3.2 `setup_status` ตรวจความพร้อมของ bucket | ⚠️ บางส่วน | preflight แบบ bounded (`max-keys=1`) มีแล้ว แต่ต้องเปิดด้วย `verify_connection=true`; ดู gap report G3 |
| §3.2 Upload พร้อม Content-Type / Cache-Control | ✅ | `s3_helper.py` — ตรงตาม ADR §4 ทุก visibility |
| §3.2 Probe ทั้ง public และ private URL | ✅ | probe ทั้ง index และ snapshot |
| §4 ขั้นตอน onboarding 4 ขั้น | ⚠️ บางส่วน | ขั้นตอนอยู่ใน ADR แต่ยังไม่ถูกย้ายเข้าคู่มือผู้ใช้ (`docs/setup.md`) — ดู gap report G1 |
| §4 ขั้นตอนที่ 1: R2 API Token "Admin Read/Write" | ⚠️ แก้แล้ว | **ADR §3 Step 2 ชนะ** — ใช้ **Object Read & Write scoped เฉพาะ bucket** เท่านั้น ห้าม Admin Read/Write |

### สิ่งที่ทำได้มากกว่าแผน

- รองรับได้ทั้ง **Cloudflare R2, AWS S3 และ MinIO** (แผนเน้น R2 เป็นหลัก)
- **ไม่ต้องมี `known_hosts` เลย** สำหรับโปรไฟล์ S3 (SFTP ยังต้อง pin host key)
- **Snapshot อัปโหลดก่อน live index** ในสาย S3 (สาย SFTP ยังเขียน index ก่อน)
- **จำกัดการอ่าน response ที่ 5 MiB** แบบ streaming (สาย SFTP ไม่มี)
- โหมด `publish.sh --ping` สำหรับ preflight แบบ bounded ไม่เขียน
- ยืนยันตัวตนของ driver ในผลลัพธ์ MCP: `storage driver: s3` และ `auth: s3-api-token`

---

## 1. บริบทและวัตถุประสงค์ (Context & Objectives)

ต้องการเพิ่ม Storage Driver ทางเลือกที่รองรับ **S3-Compatible Object Storage (เน้น Cloudflare R2)** ให้กับ `artifact-sftp` โดยมีเงื่อนไขสำคัญสูงสุด 2 ประการ:
1. **รักษา URL และระบบความปลอดภัย (Private Access Gate):** ต้องได้ Clean URL ที่คงทน ถาวร และมีระบบป้องกัน Private Artifacts ด้วยการบังคับยืนยันตัวตน (Authentication) เหมือนกับสถาปัตยกรรม SFTP เดิมทุกประการ
2. **Setup และ Onboarding ง่ายที่สุด:** ผู้ใช้ตั้งค่าครั้งแรกได้สะดวก มี Wizard/Template และคู่มือแนะนำแบบ Step-by-Step ชัดเจน

---

## 2. สถาปัตยกรรมที่เลือก (Selected Architecture: Option 1)

```text
               [AI Agent / MCP Client]
                          │
          (S3 PUT API / S3 Client / Boto3)
                          ▼
            [Cloudflare R2 Bucket (Private)]
                          ▲
                          │
            [Custom Domain / Cloudflare CDN]
             (e.g. artifacts.mycompany.com)
             ├── /public/*  ──> ปล่อยผ่าน (Public Anonymous Access)
             └── /private/* ──> Cloudflare Zero Trust Access Gate (OTP/Google Login)
```

### จุดเด่นของสถาปัตยกรรมนี้:
- **Zero Server Management:** ไม่ต้องเปิด Linux VPS, ไม่ต้องเปิดพอร์ต 22 (SSH/SFTP)
- **100% URL Parity:** โครงสร้าง URL เหมือนเดิม `https://artifacts.mycompany.com/<tool>/<visibility>/<slug>/`
- **100% Security Probe Compatibility:** สคริปต์ตรวจสอบความปลอดภัยยังคงยิง anonymous probe ได้เหมือนเดิม (หากได้ 302 ไปยัง `cloudflareaccess.com` หรือ 401/403 ถือว่า `PASS` ปลอดภัย)
- **Zero Egress Fee:** Cloudflare R2 ให้ฟรี 10GB/เดือน และไม่มีค่า Bandwidth ขาออก

---

## 3. รายละเอียดการออกแบบ (Design Blueprint)

### 3.1 การตั้งค่า Config (`~/.config/artifact-sftp/config`)
รองรับการระบุ Driver แบบ Backward Compatible:

```ini
# เลือกระหว่าง sftp (default) หรือ s3
STORAGE_DRIVER=s3

# S3 / Cloudflare R2 Settings
S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
S3_BUCKET=my-artifacts
S3_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
S3_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
S3_REGION=auto
PUBLIC_BASE_URL=https://artifacts.mycompany.com

# Optional Cloudflare Access Service Token (สำหรับ Authenticated Verification)
CF_ACCESS_CLIENT_ID=xxxxxxxxxxxxxxxx.access
CF_ACCESS_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3.2 การปรับปรุง MCP & Publisher Engine
- เพิ่ม `S3Driver` ใน Python MCP (`src/artifact_sftp_mcp/`) โดยใช้ S3 Client (เช่น `boto3` หรือ SigV4 HTTP)
- รองรับ `setup_status` และ `setup` สำหรับตรวจสอบความพร้อมของ S3 Bucket และ Permission
- อัปโหลด Object พร้อมระบุ Metadata:
  - `Content-Type: text/html; charset=utf-8`
  - `Cache-Control: public, max-age=300` (หรือ no-cache สำหรับ index)
- ทำการ probe ตรวจสอบความปลอดภัยทั้ง Public URL และ Private URL แบบเดิม

---

## 4. แผนงาน Onboarding Guide (คู่มือสำหรับผู้ใช้)

จัดทำคู่มือแบบ Step-by-Step สั้นกระชับ:
1. **ขั้นตอนที่ 1 (Cloudflare R2):** สร้าง R2 Bucket (เช่น `artifacts`) และสร้าง R2 API Token (Admin Read/Write)
2. **ขั้นตอนที่ 2 (Custom Domain):** ต่อ Custom Domain เข้ากับ R2 Bucket ใน Cloudflare Dashboard
3. **ขั้นตอนที่ 3 (Zero Trust Access):** สร้าง Access Application บน Path `artifacts.domain.com/*/private/*` กำหนดนโยบาย Allow Email / Domain OTP
4. **ขั้นตอนที่ 4 (Local Setup):** รัน `artifact_sftp.setup` หรือกรอกไฟล์ `~/.config/artifact-sftp/config` จบพร้อมใช้งาน!
