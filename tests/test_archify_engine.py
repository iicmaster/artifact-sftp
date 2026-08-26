"""Comprehensive test suite verifying the bundled Archify diagram engine within artifact-sftp."""

import json
import subprocess
import tempfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
ARCHIFY_BIN = ROOT / "tools" / "archify" / "bin" / "archify.mjs"


def test_archify_bin_exists_and_doctor_passes():
    """Verify that the bundled Archify CLI exists and passes all doctor health checks."""
    assert ARCHIFY_BIN.exists(), f"archify.mjs must exist at {ARCHIFY_BIN}"

    result = subprocess.run(
        ["node", str(ARCHIFY_BIN), "doctor"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"archify doctor failed: {result.stderr}\n{result.stdout}"
    assert "Archify is ready." in result.stdout


@pytest.mark.parametrize(
    "diagram_type,spec_filename",
    [
        ("architecture", "production-deployment.architecture.json"),
        ("workflow", "agent-tool-call.workflow.json"),
        ("sequence", "cache-miss-request.sequence.json"),
        ("dataflow", "product-analytics.dataflow.json"),
        ("lifecycle", "agent-run.lifecycle.json"),
    ],
)
def test_archify_validates_and_delivers_all_archetypes(diagram_type: str, spec_filename: str):
    """Verify that all 5 Archify archetypes validate with 9/9 showcase checks and deliver valid HTML."""
    spec_path = ROOT / "tools" / "archify" / "examples" / spec_filename
    assert spec_path.exists(), f"{spec_filename} must exist"

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
        assert val_result.returncode == 0, f"Validation failed: {val_result.stderr}\n{val_result.stdout}"
        val_data = json.loads(val_result.stdout)
        assert val_data.get("ok") is True
        checks = val_data.get("checks", [])
        assert len(checks) == 9
        assert all(c.get("ok") is True for c in checks)
        comp = val_data.get("composition", {}).get("summary", {})
        assert comp.get("errors") == 0
        assert comp.get("warnings") == 0

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
        assert del_result.returncode == 0, f"Delivery failed: {del_result.stderr}\n{del_result.stdout}"
        del_data = json.loads(del_result.stdout)
        assert del_data.get("ok") is True
        del_val = del_data.get("validation", {})
        assert del_val.get("checksPassed") == 9
        assert del_val.get("errors") == 0
        assert del_val.get("warnings") == 0

        assert output_html.exists(), f"Output HTML {output_html} must be generated"
        
        html_content = output_html.read_text(encoding="utf-8")
        assert "<svg" in html_content
        assert "data-theme" in html_content
        assert "data-preset" in html_content
        assert "Sarabun" in html_content
        assert "line-height: 1.6" in html_content
