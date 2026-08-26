"""Comprehensive test suite verifying the bundled Archify diagram engine within artifact-sftp."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIFY_BIN = ROOT / "tools" / "archify" / "bin" / "archify.mjs"


class ArchifyEngineTestCase(unittest.TestCase):
    def test_archify_bin_exists_and_doctor_passes(self):
        """Verify that the bundled Archify CLI exists and passes all doctor health checks."""
        self.assertTrue(ARCHIFY_BIN.exists(), f"archify.mjs must exist at {ARCHIFY_BIN}")

        result = subprocess.run(
            ["node", str(ARCHIFY_BIN), "doctor"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, f"archify doctor failed: {result.stderr}\n{result.stdout}")
        self.assertIn("Archify is ready.", result.stdout)

    def test_archify_validates_and_delivers_all_archetypes(self):
        """Verify that all 5 Archify archetypes validate with 9/9 showcase checks and deliver valid HTML."""
        archetypes = [
            ("architecture", "production-deployment.architecture.json"),
            ("workflow", "agent-tool-call.workflow.json"),
            ("sequence", "cache-miss-request.sequence.json"),
            ("dataflow", "product-analytics.dataflow.json"),
            ("lifecycle", "agent-run.lifecycle.json"),
        ]

        for diagram_type, spec_filename in archetypes:
            with self.subTest(diagram_type=diagram_type, spec_filename=spec_filename):
                spec_path = ROOT / "tools" / "archify" / "examples" / spec_filename
                self.assertTrue(spec_path.exists(), f"{spec_filename} must exist")

                with tempfile.TemporaryDirectory() as tmpdir:
                    output_html = Path(tmpdir) / f"{diagram_type}.html"

                    # 1. Validate spec with showcase quality profile
                    val_result = subprocess.run(
                        [
                            "node",
                            str(ARCHIFY_BIN),
                            "validate",
                            diagram_type,
                            str(spec_path),
                            "--quality",
                            "showcase",
                            "--json",
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(
                        val_result.returncode,
                        0,
                        f"Validation failed for {diagram_type}: {val_result.stderr}\n{val_result.stdout}",
                    )
                    val_data = json.loads(val_result.stdout)
                    self.assertTrue(val_data.get("ok"))
                    checks = val_data.get("checks", [])
                    self.assertEqual(len(checks), 9)
                    self.assertTrue(all(c.get("ok") is True for c in checks))
                    comp = val_data.get("composition", {}).get("summary", {})
                    self.assertEqual(comp.get("errors"), 0)
                    self.assertEqual(comp.get("warnings"), 0)

                    # 2. Deliver standalone HTML artifact
                    del_result = subprocess.run(
                        [
                            "node",
                            str(ARCHIFY_BIN),
                            "deliver",
                            diagram_type,
                            str(spec_path),
                            str(output_html),
                            "--quality",
                            "showcase",
                            "--json",
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(
                        del_result.returncode,
                        0,
                        f"Delivery failed for {diagram_type}: {del_result.stderr}\n{del_result.stdout}",
                    )
                    del_data = json.loads(del_result.stdout)
                    self.assertTrue(del_data.get("ok"))
                    del_val = del_data.get("validation", {})
                    self.assertEqual(del_val.get("checksPassed"), 9)
                    self.assertEqual(del_val.get("errors"), 0)
                    self.assertEqual(del_val.get("warnings"), 0)

                    self.assertTrue(output_html.exists(), f"Output HTML {output_html} must be generated")

                    html_content = output_html.read_text(encoding="utf-8")
                    self.assertIn("<svg", html_content)
                    self.assertIn("data-theme", html_content)
                    self.assertIn("data-preset", html_content)
                    self.assertIn("Sarabun", html_content)
                    self.assertIn("line-height: 1.6", html_content)

    def test_thai_text_units_ignores_zero_advance_combining_marks(self):
        """Verify that Thai combining marks (vowels/tones) do not inflate horizontal text units."""
        js_code = """
        import('./tools/archify/renderers/shared/utils.mjs').then(m => {
          const t1 = m.textUnits('ที่นี่');
          const t2 = m.textUnits('ผู้ใช้งาน');
          const t3 = m.textUnits('สถาปัตยกรรม');
          if (t1 !== 2 || t2 !== 6 || t3 !== 10) {
            console.error(JSON.stringify({ t1, t2, t3 }));
            process.exit(1);
          }
          console.log('OK');
        });
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", js_code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, f"Thai textUnits test failed: {result.stderr}\n{result.stdout}")
        self.assertIn("OK", result.stdout)

    def test_thai_locale_metadata_and_html_generation(self):
        """Verify that locale 'th' is accepted by schema validator and produces <html lang="th">."""
        thai_spec = {
            "schema_version": 1,
            "diagram_type": "workflow",
            "meta": {
                "title": "ระบบชำระเงินอัตโนมัติ",
                "locale": "th",
                "quality_profile": "standard"
            },
            "lanes": [
                {"id": "user_lane", "label": "ผู้ใช้งาน", "variant": "normal"},
                {"id": "sys_lane", "label": "ระบบชำระเงิน", "variant": "normal"}
            ],
            "nodes": [
                {"id": "start", "lane": "user_lane", "col": 0, "type": "frontend", "label": "กดปุ่มชำระเงิน"},
                {"id": "process", "lane": "sys_lane", "col": 1, "type": "backend", "label": "ตัดยอดบัตรเครดิต"}
            ],
            "edges": [
                {"id": "e1", "from": "start", "to": "process", "label": "ส่งคำสั่ง", "variant": "emphasis"}
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "thai-workflow.json"
            output_html = Path(tmpdir) / "thai-workflow.html"
            spec_path.write_text(json.dumps(thai_spec, ensure_ascii=False), encoding="utf-8")

            # 1. Validate spec with locale="th"
            val_result = subprocess.run(
                ["node", str(ARCHIFY_BIN), "validate", "workflow", str(spec_path), "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(val_result.returncode, 0, f"Validation failed: {val_result.stderr}\n{val_result.stdout}")
            val_data = json.loads(val_result.stdout)
            self.assertTrue(val_data.get("ok"))

            # 2. Deliver HTML with locale="th"
            del_result = subprocess.run(
                ["node", str(ARCHIFY_BIN), "deliver", "workflow", str(spec_path), str(output_html), "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(del_result.returncode, 0, f"Delivery failed: {del_result.stderr}\n{del_result.stdout}")
            self.assertTrue(output_html.exists())
            html_content = output_html.read_text(encoding="utf-8")
            self.assertIn('lang="th"', html_content)

    def test_workflow_edge_role_preservation(self):
        """Verify that edge role values (e.g. main, error, async) are preserved in rendered SVG attributes."""
        workflow_spec = {
            "schema_version": 1,
            "diagram_type": "workflow",
            "meta": {
                "title": "Edge Role Test",
                "quality_profile": "standard"
            },
            "lanes": [
                {"id": "main_lane", "label": "Main", "variant": "normal"}
            ],
            "nodes": [
                {"id": "n1", "lane": "main_lane", "col": 0, "type": "frontend", "label": "Start"},
                {"id": "n2", "lane": "main_lane", "col": 2, "type": "backend", "label": "Handler"}
            ],
            "edges": [
                {"id": "e_err", "from": "n1", "to": "n2", "label": "Failover", "variant": "security", "role": "error", "labelDy": 20}
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "role-workflow.json"
            output_html = Path(tmpdir) / "role-workflow.html"
            spec_path.write_text(json.dumps(workflow_spec), encoding="utf-8")

            del_result = subprocess.run(
                ["node", str(ARCHIFY_BIN), "deliver", "workflow", str(spec_path), str(output_html), "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(del_result.returncode, 0, f"Delivery failed: {del_result.stderr}\n{del_result.stdout}")
            html_content = output_html.read_text(encoding="utf-8")
            self.assertIn('data-edge-role="error"', html_content)

    def test_legend_measurement_and_rendered_font_size_parity(self):
        """Verify that legend measurement and rendered SVG text use the exact same font size."""
        js_code = """
        import('./tools/archify/renderers/shared/legend.mjs').then(m => {
          const entries = [
            { kind: 'k1', label: 'Primary Data Flow Stream' },
            { kind: 'k2', label: 'Secondary Analytics Pipeline' }
          ];
          const layout = { x: 30, baselineY: 400, width: 800 };
          const measured = m.measureLegend(entries, layout);
          const rendered = m.renderLegend({
            entries,
            layout,
            renderSwatch: () => '<rect width="14" height="14"/>',
            locale: 'en'
          });
          if (!rendered.includes(`font-size="${measured.fontSize}"`)) {
            console.error('Mismatch between measured and rendered font size:', measured.fontSize, rendered);
            process.exit(1);
          }
          console.log('OK');
        });
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", js_code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, f"Legend font size parity test failed: {result.stderr}\n{result.stdout}")
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
