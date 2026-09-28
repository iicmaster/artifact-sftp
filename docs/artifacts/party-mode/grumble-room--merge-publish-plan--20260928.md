# แผนรวม PR และ Publish — Grumble Room (2026-09-28)

- **Party:** The Grumble Room (Mary, John, Winston, Amelia, Sally, Grumbal)
- **วาระ:** วางแผนรวม PR ที่เปิดอยู่ แล้ว publish release
- **สถานะ:** มติผ่านเอกฉันทะ — แผนรถไฟเดียว v0.22.0 พร้อมทางหนี

## ข้อมูลประกอบมติ (Evidence)

| รายการ | สถานะ |
|---|---|
| PR #29 (docs: Windows Git Bash launcher) | เขียว 4/4, ไม่มี feedback, mergeable |
| PR #30 (fix: Windows drive paths) | เขียว 4/4, แต่ Codex ทิ้ง 2×P1 + 1×P2 ยังไม่แก้ |
| งาน S3/R2 (feat/s3-cloudflare-r2-driver) | main + uncommitted ทั้งหมด, ยังไม่มี PR |
| test_publish.sh (สาย S3) | FAIL 1 check — refooter ไม่ลบ footer เก่า (count 2) |
| tests/test_s3_helper.py | `import pytest` แต่ CI ไม่มี pytest → CI แดงทันทีถ้า push |
| main vs tag | main (0.21.3) นำ tag v0.21.3 อยู่ 2 commits (#27, #28) — เป็นหนี้ release |

## ลำดับงานที่มติกำหนด

1. stash งาน S3 ทั้งกอง (รวม untracked) — ให้ต้นไม้สะอาด
2. merge PR #29 ทันที (เขียว, ไม่มี feedback)
3. แก้ 3 จุด Codex บน PR #30:
   - P1: `service.py` — marker patterns ต้องรับ UNC path (`\\server\share`)
   - P2: `service.py` — การแปลง `/e/...` → `e:/...` ต้อง gate ให้ทำเฉพาะ Windows
   - P1: `read-artifact.sh` — resolver ต้องรับ drive path (`E:\...`) เป็น absolute reference
   แล้ว push → รอ CI 4/4 + Codex ไม่ทิ้ง issue ใหม่ → merge
4. กลับสาย S3: แก้ refooter ใน publish.sh + เขียน test_s3_helper เป็น unittest → commit → rebase บน main → เปิด PR → รอ CI + Codex → merge
5. bump เวอร์ชัน 0.22.0 (marketplace.json, plugin.json ×2, plugin.json root, pyproject.toml, CHANGELOG.md) → tag v0.22.0 → `gh release create`

## ทางหนี (Contingency)

หากสาย S3 สะดุดเกินรอบวันนี้: ตัด release **v0.21.4** (PR #29 + #30 + commits #27/#28 ที่ค้างบน main) ออกก่อน แล้วให้ S3 เดินต่อเป็น v0.22.0

## เงื่อนไขเหล็กของ Grumbal

ห้าม merge PR ใดตราบใดที่ยังมี review issue แอคทีฟ ไม่ว่า CI จะเขียวเพียงใด

## ลำดับบังคับด้วยไฟล์ (Winston)

งาน S3 แตะไฟล์เดียวกับทั้งสอง PR (`service.py`, `read-artifact.sh`, `setup.md`) — ต้องรวม PR เล็กก่อน จึง rebase สาย S3 บน main ใหม่ได้โดยไม่ conflict ซ้ำซ้อน
