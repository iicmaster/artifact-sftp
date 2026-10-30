# รายงาน Gap: แผน S3/R2 ↔ โค้ดจริง

- **แผนที่ตรวจสอบ:** [`docs/plans/s3-cloudflare-r2-plan.md`](s3-cloudflare-r2-plan.md)
- **ADR:** [`docs/adr/0001-s3-cloudflare-r2-driver.md`](../adr/0001-s3-cloudflare-r2-driver.md)
- **วันที่ตรวจ:** 2026-10-21 (หลัง release v0.22.1)
- **บันทึกบน:** `origin/main` @ `e2ec858` (v0.22.1) — G15 และการอ้างเลข PR ถูกแก้ตาม PR #35; ดูคอมมิตของ PR นั้นสำหรับสถานะล่าสุด
- **ขอบเขต:** ตรวจจากซอร์สโค้ดแบบ read-only สองด้าน — (1) setup/onboarding/config (2) publish/read/security-probe/transport
- **หมายเหตุ:** ไม่มีการรันสคริปต์ใด ๆ ตามนโยบาย `AGENTS.md` (MCP-only) — ทุกข้อสรุปมาจากการอ่านโค้ดและอ้างอิง assertion ที่ยังไม่ถูกรันใน `test_setup.sh` / `test_s3_helper.py`

---

## สรุป

โค้ดส่วนใหญ่ของแผนถูก implement ครบและตรงตาม ADR — แต่ยังมีช่องโหว่เชิงความปลอดภัย 1 จุดที่ **เปิดในโค้ดที่ ship ไปแล้ว** และช่องว่างด้านเอกสาร/ประสบการณ์ผู้ใช้อีกหลายจุด

| ระดับ | จำนวน | หัวข้อ |
|---|---|---|
| 🔴 P1 | 1 | S3 overwrite guard fail-open เมื่อเกิด transport error (G1) |
| 🟠 P2 | 6 | คู่มือ onboarding ไม่มีที่ไหนเลย (G2), readiness ไม่ยืนยัน bucket (G3), Transform Rule ไม่มี (G4), wizard/config ตายตอนตั้งค่า (G5), `docs/setup.md` เป็น SFTP-only (G6), probe ไม่ครอบ `r2.dev` + ลำดับ fail-closed ไม่ถูกสื่อ (G7) |
| 🟡 P3 | 9 | `S3_BUCKET`/`S3_REGION` ไม่ validate (G8, G9), default URL ของ wizard เป็น third-party (G10), คำอธิบาย agent-facing ยังพูดแต่ SFTP (G11), permission `s3:ListBucket` ไม่ได้ระบุ (G12), ไม่มี test ระดับ publish.sh สำหรับ S3 (G13), `Cache-Control` ไม่ถูก verify ฝั่ง response (G14), `--list` exit semantics ต่างกัน (G16), สาย SFTP มี fail-open เดียวกัน (G17) |

---

## 🔴 P1 — G1: S3 overwrite guard fail-open เมื่อเกิด transport error

**สัญญาที่โค้ด claim:** `s3_helper.py` ระบุว่า *"Storage refused or errored: exit 4 so callers never confuse 'probe failed' with 'probe answered 404' — the overwrite guard depends on that distinction"* และ CHANGELOG ของ v0.22.0 เขียนว่า *"HEAD failures exit with a distinct code 4 so a refused probe is never mistaken for a missing slug"*

**สิ่งที่เกิดจริง:** การแยกแยะนี้ครอบคลุมเฉพาะ **HTTP status code** เท่านั้น — transport error (DNS ล้ม, connection refused, TLS handshake ล้ม, socket timeout) ตกไปที่ `except Exception` → `sys.exit(<ข้อความ>)` ซึ่งออกด้วย **status 1** ซึ่งเป็นรหัสเดียวกับ "404 = ไม่มีอยู่จริง"

ผลคือ `publish.sh` อ่าน exit 1 ว่า *"the slug is genuinely absent — safe to create"* แล้วอัปโหลดทับ **โดยไม่ผ่าน custody check ใด ๆ** — เขียนทับ artifact ของผู้อื่นได้

ยืนยันด้วยการรันจริง: transport error → `SystemExit.code` เป็น string → process exit status **1** (HTTP 403 → 4)

**จุดที่ต้องแก้:** `s3_helper.py` — `read_cfg`, `S3Client.__init__`, `_request`'s `except Exception`, `_bounded_read` (2 จุด), `put_object`, `get_object`, `delete_object`, `list_objects_v2_paged` ทั้งหมดต้องออกด้วย **4**; กัก `1` ไว้ให้ "404 จริง" เท่านั้น

**สถานะ: แก้แล้วใน PR #35** — ครอบคลุม HTTP refusal, transport error และ uncaught exception ในตัว helper ทุกทาง (รวม `urlparse` ที่พังก่อนสร้าง request, body read ที่ตายกลางทางใน HTTPError handler และ stderr ที่เขียนไม่ได้) เหลือเพียงขอบของ shell ที่ถือว่าเป็นเสียงของ environment ไม่ใช่โค้ด

> หมายเหตุ: สาย SFTP มีช่องโหว่เดียวกัน (`publish.sh` ถือว่า non-zero = absent) แต่สาย SFTP ไม่ได้ *claim* ความแตกต่างนี้ จึงไม่ใช่ regression — แต่เป็นจุดที่ควรแก้ต่อในรอบถัดไป **แก้แล้ว 2026-10-30 — ดูแถว G17**

---

## 🟠 P2

### G2 — ไม่มีคู่มือ onboarding R2 ที่ผู้ใช้มองเห็น

แผน §1 สัญญาว่าจะมี "Wizard/Template และคู่มือแนะนำแบบ Step-by-Step" — แต่ความรู้ทั้งหมดอยู่ใน ADR ซึ่งเป็น *decision record* ไม่ใช่คู่มือ ส่วนที่ผู้ใช้เห็นมีแค่ 6 bullet ใน `skills/artifact-sftp/references/setup.md` ที่ไม่มีลำดับ ไม่มีชื่อ rule ไม่มี path `*/private/*` และ `docs/setup.md` (คู่มือหลัก) ไม่มีคำว่า R2/S3/bucket เลย

**แก้:** เพิ่มหัวข้อ "Storage Option 2 — Cloudflare R2 / S3" ใน `docs/setup.md` โดยทำซ้ำลำดับ 6 ขั้นจาก ADR §3 พร้อมชื่อ Transform Rule, เงื่อนไข When/Action และตาราง config key ของ S3

### G3 — readiness ไม่ยืนยัน bucket จริง

`setup.sh --status` ไม่แตะเน็ตเลย — เช็คแค่ config ที่มีอยู่ ดังนั้น `ready: true` สามารถรายงานได้แม้ key id/secret/bucket/endpoint ผิดทั้งหมด การ probe มีอยู่แต่อยู่บน path ที่ต้องเปิด `verify_connection=true` และพิสูจน์ได้แค่ "reach + list permission" ไม่ใช่ write permission และไม่ใช่ "bucket นี้จริง"

**แก้:** ให้ wizard เรียก verify หลังเขียน config แล้วรายงานสถานะแยก: `bucket: reachable` / `credentials: rejected (403)` / `bucket: not found (404)` / `write permission: not verified`

### G4 — Transform Rule ที่ไม่ได้ตั้ง แสดงเป็น error ที่ทำให้เข้าใจผิดหลังอัปโหลดเสร็จแล้ว

URL สะอาด `.../slug/` จะได้ 404 จาก R2 custom domain ถ้าไม่มี Transform Rule → publisher ออก exit 6 ("uploaded but does not serve the expected content") หรือ exit 8 (private probe inconclusive) โดย **ไม่เคยพูดถึง custom domain หรือ Transform Rule** และ object ถูกอัปโหลดไปแล้ว

**แก้:** ในสาย S3 ของ `publish.sh` ให้ตรวจ 404/301 บน path ที่ลงท้าย `/` แล้วแนะนำเจาะจงเรื่อง Transform Rule (ADR 0001 Step 5) ก่อน error ทั่วไป

### G5 — wizard และ setup script เข้าไม่ถึงสำหรับมนุษย์

ทั้ง `setup.sh` และ `setup-wizard.sh` ออกด้วย exit 10 เว้นแต่มี `ARTIFACT_SFTP_MCP_CALL=1` ซึ่ง**ไม่ปรากฏในไฟล์ `.md` ใดเลย** ขณะที่แผน §4 บอกให้ "รัน `artifact_sftp.setup`" — แต่ MCP tool นั้นเป็น **read-only** (ไม่เขียนอะไรเลย) และ CHANGELOG ของ v0.22.0 ก็เขียนผิดว่ามัน "writes and validates S3 profiles"

**แก้:** เอกสument จุดเรียกที่ถูกต้องพร้อมตัวแปร env, และแก้ CHANGELOG ให้บอกว่า `setup.sh`/`setup-wizard.sh` เป็นผู้เขียน config ส่วน `artifact_sftp.setup` แค่รายงาน

### G6 — `docs/setup.md` มีแต่ schema ของ SFTP

ตาราง config ที่ `docs/setup.md:182-196` ให้ไว้มีแต่ `SFTP_*` และประโยค "an unknown key is a hard error" ก็ดันผู้ใช้ไม่ให้เพิ่ม `S3_*` → โปรไฟล์ที่เขียนตามคู่มือนี้จะถูก `setup.sh --status` ปฏิเสธ

**แก้:** ทำให้ตาราง schema เป็น driver-aware (สองชุดแถว เลือกตาม `STORAGE_DRIVER`)

### G7 — probe ครอบแค่ custom domain และลำดับ fail-closed ไม่ถูกสื่อถึงผู้ใช้

ADR §3 Step 1 กำหนดให้ **ปิด `r2.dev` public bucket URL** เพื่อกันการหลุด Access — แต่ probe ของ publisher ยิงแค่ `PUBLIC_BASE_URL` ไม่มีทางตรวจ `r2.dev` ได้ และ `references/setup.md` เรียง Steps 1–5 เป็น bullet แบนๆ ทำให้เจ้าของอาจผูก custom domain **ก่อน** ตั้ง Access Application ซึ่งเป็นหน้าต่างเปิดรับความเสี่ยงที่ ADR บอกว่าห้ามเกิด

**แก้:** (ก) เรียง `references/setup.md` เป็นลำดับตาม ADR และเขียนกำกับว่า "Access ก่อนผูก domain" (ข) ระบุชัดว่า publish-time probe รับรองเฉพาะ custom domain และ `r2.dev` ต้องตรวจเองใน console

---

## 🟡 P3

| ID | ประเด็น | ตำแหน่ง | ข้อเสนอแก้ |
|---|---|---|---|
| G8 | `S3_BUCKET` ผ่านแค่ `_shell_safe` — `My_Artifacts` (ตัวพิมพ์ใหญ่+underscore) ผ่าน setup แต่ R2 ปฏิเสธ | `setup.sh:335` | validate ตามกฎชื่อ bucket ของ S3 (เล็ก 3–63 ไม่มี `_`) |
| G9 | `S3_REGION` ไม่อยู่ในรายการ key ที่ status ต้องมี ไม่ถูก validate และไม่ถูกแสดงผล — ค่าที่ใช้จริง (`auto`) อาจไม่ใช่ค่าที่เจ้าของเขียน | `setup.sh:150,335`; `s3_helper.py:85` | เพิ่มเข้ารายการ required + แสดงค่าที่มีผลจริง + บังคับ `auto` เมื่อ endpoint เป็น `.r2.cloudflarestorage.com` |
| G10 | wizard ใช้ `PUBLIC_BASE_URL` default เป็น `https://artifacts.ngs.bz` (โดเมน third-party) — เจ้าของ R2 ที่กด Enter จะได้ config ที่ "ถูกแต่ผิด" | `setup-wizard.sh:158` | ในสาย S3 ให้ prompt แบบ required ไม่มี default |
| G11 | คำอธิบายฝั่ง agent ยังบอกว่าเป็น SFTP ทั้งหมด (`server.py`, `SKILL.md`, `artifact-sftp-read/SKILL.md` ที่ยังไม่มี `remote_s3`) | `server.py:43,60,118`; `skills/artifact-sftp/SKILL.md:74`; `skills/artifact-sftp-read/SKILL.md:30` | ทำให้เป็น driver-neutral และระบุว่า `storage_driver` ในผลลัพธ์บอก backend ที่ใช้ |
| G12 | ต้องมี `s3:ListBucket` แต่เอกสารบอกแค่ "Object Read & Write" — ถ้า token ไม่มี ListBucket → preflight และ `unpublish` จะพังโดยไม่มีข้อความชัด | `s3_helper.py:268,353,371`; `references/setup.md:19` | ระบุ permission ที่ต้องใช้ให้ครบ และทำ `test_connection` fallback ไป HEAD เมื่อ LIST โดน 403 |
| G13 | ไม่มี test ระดับ `publish.sh` สำหรับสาย S3 เลย — probe exit 7/8, ลำดับ snapshot→index, custody refusal ทั้งหมดถูกทดสอบผ่านสาย SFTP เท่านั้น | `skills/artifact-sftp/scripts/test_publish.sh` (ไม่มีเคส s3) | stub `s3_helper.py` บน PATH แล้วเพิ่มเคส S3 |
| G14 | `Cache-Control` / `Content-Type` ถูกตั้งตอน PUT แต่ไม่เคยถูกตรวจบน response — edge rule ที่ rewrite header จะทำลาย ADR invariant แบบเงียบๆ | `publish.sh` (`verify_url` เทียบแค่ body hash) | ตรวจ response header ใน `verify_url` แล้ว treat mismatch เป็น exit 6 |
| G15 | version discovery กลืน error (`\|\| true`) → `VER` ตกกลับเป็น 1 ได้ และ snapshot เดิมถูกเขียนทับในวินาทีเดียวกัน | `publish.sh:215` (สาย S3) | ✅ **แก้แล้วใน PR #35** — สาย S3 ล้มเหลวแบบ fail closed (exit 5) แล้ว ส่วนสาย SFTP ยังเป็น `\|\| true` → ดู G17 |
| G16 | `--list` exit semantics ต่างกัน: S3 ออก 0 เสมอ, SFTP ผ่าน OpenSSH ออก non-zero ถ้าโฟลเดอร์ไม่มี | `publish.sh:227` vs `:232` | ปรับให้ตรงกัน (ผลกระทบต่ำ เพราะ MCP `list` เป็น local-only) |
| G17 | **สาย SFTP มีช่องโหว่ fail-open แบบเดียวกัน** — version discovery กลืน error และ existence check ถือว่าทุก failure เป็น "ไม่มีอยู่" ทำให้ข้าม custody check ได้ | `publish.sh:213-223, 399-407`; `sftp_helper.py:81-85, 126-129` | **✅ แก้แล้ว 2026-10-30 (branch `fix/sftp-fail-closed-custody`)** — `sftp_helper.py` ใช้สัญญา 0/1/2/4/10 (exit 1 = confirmed remote ENOENT เท่านั้น เหมือน `s3_helper.py`) ครบทั้ง connect/exists/versions/get/list/upload/delete; `publish.sh` จัด tri-state ทั้งสาย paramiko และ OpenSSH (root-liveness probe แยก connection, จำแนกด้วยผลลัพธ์ไม่ใช่ข้อความ stderr), version listing fail-closed แบบ capture rc ก่อน pipeline, และแก้ delete ที่ใช้ `ls -d` (flag ที่ sftp(1) ไม่มี) จนรายงาน takedown เทียมว่าสำเร็จ — เศษที่ยอมรับไว้: TOCTOU ระหว่าง exists→upload (เท่าเดิมทั้งสอง driver), slug dir ที่มีอยู่แต่ปฏิเสธ listing บน OpenSSH (`--force` คือทางออก), และ version race วินาทีเดียวกัน |

---

## สิ่งที่โค้ดทำได้มากกว่าแผน (ควรบันทึกไว้)

1. **Validation เข้มกว่าแผนมาก** — `S3_ENDPOINT` ถูกปฏิเสธเมื่อไม่มี authority / มี path prefix / มี query / มี fragment / ไม่ใช่ HTTPS; `PUBLIC_BASE_URL` ต้องเป็น HTTPS origin ที่มี host; config ถูกตรวจ unknown key, ค่าว่าง, shell metacharacter และ key ซ้ำ; symlink ถูกปฏิเสธ
2. **สุขอนามัยของ secret แน่นกว่าแผน** — secret รับจาก stdin เท่านั้น (ไม่ผ่าน argv), `umask 077` + `chmod 600` config + `chmod 700` โฟลเดอร์, `CF_ACCESS_CLIENT_ID`/`SECRET` ต้องมาเป็นคู่หรือไม่มีเลย
3. **มี preflight แบบ bounded และไม่เขียน** ซึ่งแผนไม่ได้ขอ — นี่คือสิ่งที่ทำให้ `verify_connection=true` มีความหมายกับ S3
4. **รายงาน driver/auth แบบ machine-readable** — `storage driver: s3` และ `auth: s3-api-token` เป็นฟิลด์ผลลัพธ์ MCP ระดับแรก
5. **รองรับ driver มากกว่าที่แผนขอ** — R2, AWS S3 และ MinIO
6. **การ harden transport ที่มีผลจริง** — HEAD ที่ถูกปฏิเสธออก exit 4, snapshot อัปโหลดก่อน live index, ตรวจขนาด 5 MiB ทั้งก่อนอัปโหลดและหลังดาวน์โหลด, อ่าน response แบบ bounded

---

## สิ่งที่ยืนยันไม่ได้

- **Cloudflare ฝั่ง dashboard** — ว่าคำสันวนใน R2/Access/Transform Rule ยังตรงกับ ADR §3, SigV4 ของเราถูก R2 ยอมรับหรือไม่, `S3_REGION=auto` ยังถูกต้องหรือไม่
- **พฤติกรรมจริงของ Cloudflare Access** — ถ้า deployment ตอบ **HTTP 200 พร้อม login page** แทน 302 → probe จะได้ hash mismatch → exit 8 → private publish ทุกตัวจะ fail เป็น "inconclusive" (fail-closed แบบ false negative เหมือนกันทั้งสอง driver)
- **`s3:ListBucket` อยู่ในสิทธิ์ "Object Read & Write" ของ R2 หรือไม่** — G12 จึงเป็นความเสี่ยง mismatch ไม่ใช่ข้อผิดพลาดที่ยืนยันแล้ว
- **end-to-end กับ R2 จริง** — ไม่มี integration test ในรีโป; หลักฐาน S3 ทั้งหมดอยู่ที่ระดับ unit
- **Windows/WSL ของสาย S3** — `s3_helper.py` ใช้ stdlib ล้วนจึงควรไม่มีปัญหา แต่สาย S3 ของ `read-artifact.sh`/`publish.sh` ไม่เคยถูกรันบน Windows ในไฟล์ที่อ่าน
