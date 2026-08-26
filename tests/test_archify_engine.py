"""Verification test suite for the bundled Archify diagram engine."""

import json
import subprocess
import tempfile
from pathlib import Path

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


def test_archify_renders_architecture_artifact():
    """Verify that Archify can validate and deliver a showcase architecture diagram."""
    spec_path = ROOT / "tools" / "archify" / "examples" / "web-app.architecture.json"
    assert spec_path.exists(), "web-app.architecture.json must exist"

    with tempfile.TemporaryDirectory() as tmpdir:
        output_html = Path(tmpdir) / "web-app.html"

        # 1. Validate spec
        val_result = subprocess.run(
            [
                "node",
                str(ARCHIFY_BIN),
                "validate",
                "architecture",
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

        # 2. Deliver HTML
        del_result = subprocess.run(
            [
                "node",
                str(ARCHIFY_BIN),
                "deliver",
                "architecture",
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
        assert output_html.exists()
        html_content = output_html.read_text(encoding="utf-8")
        assert "<svg" in html_content
        assert "data-theme" in html_content
        assert "Sample Web App Diagram" in html_content
