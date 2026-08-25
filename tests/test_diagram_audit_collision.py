"""Test suite for Diagram Collision, Text Overlap, and Zero-Collision Integrity Checks."""

import re
from pathlib import Path


def audit_svg_collisions(html_content: str) -> dict:
    """Simulates artifact-audit Dimensions 1 & 2 collision, typography, and overlap analysis."""
    findings = []
    
    # 1. Detect raw Mermaid in HTML
    if re.search(r'<pre\s+class=["\']mermaid["\']', html_content, re.IGNORECASE) or re.search(r'```mermaid', html_content):
        if not re.search(r'<svg[\s>]', html_content, re.IGNORECASE):
            findings.append({"level": "BLOCK", "rule": "raw_mermaid_in_html", "msg": "Raw Mermaid code block found in HTML without static SVG rendering."})

    # 2. Check Thai Typography & CSS Line-Height in Thai text blocks
    has_thai = bool(re.search(r'[\u0e00-\u0e7f]', html_content))
    if has_thai:
        # Check for explicit line-height declarations in CSS / style tags
        lh_matches = re.findall(r'line-height\s*:\s*([0-9.]+)(px|em|rem|%)?', html_content, re.IGNORECASE)
        for val_str, unit in lh_matches:
            try:
                val = float(val_str)
                # If unitless, em, or rem:
                if unit in ("", "em", "rem"):
                    if val < 1.3:
                        findings.append({
                            "level": "BLOCK",
                            "rule": "thai_line_height_critical",
                            "msg": f"Thai text line-height ({val}) is below 1.3, causing severe vowel/tone-mark overlap."
                        })
                    elif val < 1.5:
                        findings.append({
                            "level": "WARN",
                            "rule": "thai_line_height_tight",
                            "msg": f"Thai text line-height ({val}) is below recommended 1.5 baseline."
                        })
            except ValueError:
                pass

    # 3. Extract inline SVGs
    svg_matches = re.findall(r'<svg[\s\S]*?</svg>', html_content, re.IGNORECASE)
    for idx, svg in enumerate(svg_matches, 1):
        # 4. Check for unbadged text labels over connection lines
        groups = re.findall(r'<g[\s\S]*?</g>', svg, re.IGNORECASE)
        for g in groups:
            has_text = bool(re.search(r'<text[\s\S]*?</text>', g, re.IGNORECASE))
            has_path_marker = bool(re.search(r'marker-end=', g, re.IGNORECASE))
            has_rect_badge = bool(re.search(r'<rect[\s\S]*?/>', g, re.IGNORECASE))
            
            if has_text and has_path_marker and not has_rect_badge:
                findings.append({
                    "level": "BLOCK",
                    "rule": "unbadged_edge_label",
                    "msg": f"SVG #{idx}: Edge label <text> is directly placed on <path> without background <rect> pill badge."
                })

        # 5. Check Thai multiline text vertical step (dy) in SVG
        if has_thai:
            tspan_matches = re.findall(r'<tspan[^>]*\s+dy=["\']([0-9.]+)(em|px)?["\'][^>]*>([\s\S]*?)</tspan>', svg, re.IGNORECASE)
            for dy_str, unit, tspan_text in tspan_matches:
                if re.search(r'[\u0e00-\u0e7f]', tspan_text):
                    try:
                        dy_val = float(dy_str)
                        if dy_val > 0 and (unit == "em" or unit == ""):
                            if dy_val < 1.3:
                                findings.append({
                                    "level": "BLOCK",
                                    "rule": "thai_svg_multiline_overlap",
                                    "msg": f"SVG #{idx}: Thai <tspan> dy step ({dy_val}em) < 1.3em causes tone mark collision."
                                })
                            elif dy_val < 1.5:
                                findings.append({
                                    "level": "WARN",
                                    "rule": "thai_svg_multiline_tight",
                                    "msg": f"SVG #{idx}: Thai <tspan> dy step ({dy_val}em) < 1.5em."
                                })
                    except ValueError:
                        pass

        # 6. Check for hardcoded horizontal scroll on diagram cards
        if re.search(r'class=["\'][^"\']*diagram-card[^"\']*["\'][^>]*style=["\'][^"\']*overflow-x:\s*(?:scroll|auto)', html_content, re.IGNORECASE):
            findings.append({
                "level": "BLOCK",
                "rule": "overview_horizontal_scroll",
                "msg": "Diagram card forces overflow-x on primary overview."
            })

    # 7. Check Viewport Lightbox Engine Invariants if Lightbox dialog is present
    if re.search(r'<dialog[^>]*class=["\'][^"\']*diagram-lightbox', html_content, re.IGNORECASE):
        # Must have two-tier viewport and canvas structure
        has_viewport = bool(re.search(r'class=["\'][^"\']*lightbox-viewport', html_content, re.IGNORECASE))
        has_canvas = bool(re.search(r'class=["\'][^"\']*lightbox-canvas', html_content, re.IGNORECASE))
        if not (has_viewport and has_canvas):
            findings.append({
                "level": "BLOCK",
                "rule": "missing_lightbox_canvas_structure",
                "msg": "Lightbox lacks mandatory two-tier .lightbox-viewport and .lightbox-canvas container."
            })

        # Must use transform translate + scale matrix (never raw scale alone)
        has_translate = bool(re.search(r'(?:style\.transform|transform)\s*[:=]\s*[`\'"].*translate\(', html_content, re.IGNORECASE))
        if not has_translate:
            findings.append({
                "level": "BLOCK",
                "rule": "missing_lightbox_translate_matrix",
                "msg": "Lightbox script lacks translate(x, y) transform matrix engine."
            })

        # Must have drag-to-pan event listeners
        has_drag = bool(re.search(r'mousedown', html_content, re.IGNORECASE) and re.search(r'mousemove', html_content, re.IGNORECASE))
        if not has_drag:
            findings.append({
                "level": "BLOCK",
                "rule": "missing_lightbox_drag_pan",
                "msg": "Lightbox script lacks drag-to-pan mouse event handling."
            })

    verdict = "PASS"
    if any(f["level"] == "BLOCK" for f in findings):
        verdict = "BLOCK"
    elif any(f["level"] == "WARN" for f in findings):
        verdict = "WARN"

    return {"verdict": verdict, "findings": findings}


def test_clean_diagram_with_badges_passes():
    """Verify that a diagram with proper pill badges and clean orthogonal routing passes."""
    demo_file = Path("docs/artifacts/diagram-ergonomics-demo.html")
    assert demo_file.exists(), "demo file must exist"
    
    html = demo_file.read_text(encoding="utf-8")
    result = audit_svg_collisions(html)
    
    assert result["verdict"] == "PASS"
    assert len(result["findings"]) == 0


def test_subagent_generated_artifact_passes_all_gates():
    """Verify that the test artifact created by the subagent satisfies all 5 Pan-Zoom & Typography invariants."""
    artifact_file = Path("docs/artifacts/test-subagent-panzoom.html")
    assert artifact_file.exists(), "subagent artifact file must exist"

    html = artifact_file.read_text(encoding="utf-8")
    result = audit_svg_collisions(html)

    assert result["verdict"] == "PASS", f"Artifact findings: {result['findings']}"
    assert len(result["findings"]) == 0


def test_codex_generated_artifact_passes_all_gates():
    """Verify that the test artifact created by Codex satisfies all 5 Pan-Zoom & Typography invariants."""
    artifact_file = Path("docs/artifacts/test-codex-panzoom.html")
    assert artifact_file.exists(), "codex artifact file must exist"

    html = artifact_file.read_text(encoding="utf-8")
    result = audit_svg_collisions(html)

    assert result["verdict"] == "PASS", f"Artifact findings: {result['findings']}"
    assert len(result["findings"]) == 0


def test_unbadged_colliding_label_is_blocked():
    """Verify that connection text without a background badge is caught and BLOCKED."""
    bad_html = """
    <div class="diagram-card">
      <svg viewBox="0 0 800 400">
        <path d="M 100 100 L 400 100" stroke="#fff" marker-end="url(#arrow)"/>
        <g>
          <!-- Unbadged text directly over line: Collision! -->
          <path d="M 100 200 L 400 200" stroke="#fff" marker-end="url(#arrow)"/>
          <text x="250" y="200">Raw Overlapping Text</text>
        </g>
      </svg>
    </div>
    """
    result = audit_svg_collisions(bad_html)
    assert result["verdict"] == "BLOCK"
    assert any(f["rule"] == "unbadged_edge_label" for f in result["findings"])


def test_raw_mermaid_in_html_is_blocked():
    """Verify that raw Mermaid in HTML candidate is blocked."""
    raw_mermaid_html = """
    <html>
      <body>
        <pre class="mermaid">
          flowchart LR
            A --> B
        </pre>
      </body>
    </html>
    """
    result = audit_svg_collisions(raw_mermaid_html)
    assert result["verdict"] == "BLOCK"
    assert any(f["rule"] == "raw_mermaid_in_html" for f in result["findings"])


def test_thai_line_height_gates():
    """Verify that Thai text with line-height < 1.3 is blocked and < 1.5 is warned."""
    critical_thai_html = """
    <html>
      <head><style>p { line-height: 1.1; font-family: Sarabun; }</style></head>
      <body><p>การทำงานของระบบประมวลผลคำสั่งซื้อ</p></body>
    </html>
    """
    res1 = audit_svg_collisions(critical_thai_html)
    assert res1["verdict"] == "BLOCK"
    assert any(f["rule"] == "thai_line_height_critical" for f in res1["findings"])

    warn_thai_html = """
    <html>
      <head><style>p { line-height: 1.4; font-family: Sarabun; }</style></head>
      <body><p>การทำงานของระบบประมวลผลคำสั่งซื้อ</p></body>
    </html>
    """
    res2 = audit_svg_collisions(warn_thai_html)
    assert res2["verdict"] == "WARN"
    assert any(f["rule"] == "thai_line_height_tight" for f in res2["findings"])

    good_thai_html = """
    <html>
      <head><style>p { line-height: 1.6; font-family: Sarabun; }</style></head>
      <body><p>การทำงานของระบบประมวลผลคำสั่งซื้อ</p></body>
    </html>
    """
    res3 = audit_svg_collisions(good_thai_html)
    assert res3["verdict"] == "PASS"


def test_thai_svg_multiline_step_gate():
    """Verify that Thai multiline <tspan dy> in SVG with dy < 1.3em is blocked."""
    bad_svg = """
    <div class="diagram-card">
      <svg viewBox="0 0 400 200">
        <text x="20" y="30">
          <tspan x="20" dy="0">ระบบประมวลผลข้อมูลหลัก</tspan>
          <tspan x="20" dy="1.1em">เชื่อมต่อฐานข้อมูลคำสั่งซื้อ</tspan>
        </text>
      </svg>
    </div>
    """
    result = audit_svg_collisions(bad_svg)
    assert result["verdict"] == "BLOCK"
    assert any(f["rule"] == "thai_svg_multiline_overlap" for f in result["findings"])

    good_svg = """
    <div class="diagram-card">
      <svg viewBox="0 0 400 200">
        <text x="20" y="30">
          <tspan x="20" dy="0">ระบบประมวลผลข้อมูลหลัก</tspan>
          <tspan x="20" dy="1.6em">เชื่อมต่อฐานข้อมูลคำสั่งซื้อ</tspan>
        </text>
      </svg>
    </div>
    """
    good_res = audit_svg_collisions(good_svg)
    assert good_res["verdict"] == "PASS"


def test_broken_lightbox_without_pan_zoom_is_blocked():
    """Verify that a lightbox missing two-tier canvas, translate transform, or mouse drag is blocked."""
    broken_lightbox_html = """
    <html>
      <body>
        <dialog class="diagram-lightbox">
          <div class="diagram-lightbox__detail">
            <!-- Missing .lightbox-viewport and .lightbox-canvas -->
          </div>
        </dialog>
        <script>
          // Missing translate(X, Y) and drag events
          source.style.transform = `scale(${scale})`;
        </script>
      </body>
    </html>
    """
    res = audit_svg_collisions(broken_lightbox_html)
    assert res["verdict"] == "BLOCK"
    assert any(f["rule"] == "missing_lightbox_canvas_structure" for f in res["findings"])
    assert any(f["rule"] == "missing_lightbox_translate_matrix" for f in res["findings"])
    assert any(f["rule"] == "missing_lightbox_drag_pan" for f in res["findings"])
