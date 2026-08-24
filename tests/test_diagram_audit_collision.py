"""Test suite for Diagram Collision, Text Overlap, and Zero-Collision Integrity Checks."""

import re
from pathlib import Path


def audit_svg_collisions(html_content: str) -> dict:
    """Simulates artifact-audit Dimension 2 collision and overlap analysis on SVG content."""
    findings = []
    
    # 1. Detect raw Mermaid in HTML
    if re.search(r'<pre\s+class=["\']mermaid["\']', html_content, re.IGNORECASE) or re.search(r'```mermaid', html_content):
        if not re.search(r'<svg[\s>]', html_content, re.IGNORECASE):
            findings.append({"level": "BLOCK", "rule": "raw_mermaid_in_html", "msg": "Raw Mermaid code block found in HTML without static SVG rendering."})

    # 2. Extract inline SVGs
    svg_matches = re.findall(r'<svg[\s\S]*?</svg>', html_content, re.IGNORECASE)
    for idx, svg in enumerate(svg_matches, 1):
        # 3. Check for unbadged text labels over connection lines
        # Detect <g> groups containing text along connections
        groups = re.findall(r'<g[\s\S]*?</g>', svg, re.IGNORECASE)
        for g in groups:
            has_text = bool(re.search(r'<text[\s\S]*?</text>', g, re.IGNORECASE))
            has_path_marker = bool(re.search(r'marker-end=', g, re.IGNORECASE))
            has_rect_badge = bool(re.search(r'<rect[\s\S]*?/>', g, re.IGNORECASE))
            
            # If a group has text along a connection line or marker without a rect badge
            if has_text and has_path_marker and not has_rect_badge:
                findings.append({
                    "level": "BLOCK",
                    "rule": "unbadged_edge_label",
                    "msg": f"SVG #{idx}: Edge label <text> is directly placed on <path> without background <rect> pill badge."
                })

        # 4. Check for hardcoded horizontal scroll on diagram cards
        if re.search(r'class=["\'][^"\']*diagram-card[^"\']*["\'][^>]*style=["\'][^"\']*overflow-x:\s*(?:scroll|auto)', html_content, re.IGNORECASE):
            findings.append({
                "level": "BLOCK",
                "rule": "overview_horizontal_scroll",
                "msg": "Diagram card forces overflow-x on primary overview."
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
