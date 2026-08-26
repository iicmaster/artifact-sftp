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


if __name__ == "__main__":
    unittest.main()
