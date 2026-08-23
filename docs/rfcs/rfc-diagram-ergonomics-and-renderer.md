# RFC: Unified Diagram Architecture, Renderer Pipeline & Ergonomics

**Tracking Issues:**
- GitHub Issue #21: *Skills prescribe Mermaid and artifact-audit blocks publish on its syntax, but publish.sh ships no renderer*
- GitHub Issue #23: *feat(visual-illustrator, show-me): Avoid horizontal scroll in diagrams, enforce 100% responsive fit with a detail viewport*

**Author:** Grumble Room Architecture Team & Master  
**Status:** Accepted / Finalized  
**Decision:** Adopt **Option 4 (Static Sanitized Inline SVG Delivery)** for published HTML artifacts.  
**Review basis:** Cross-Vendor Review synthesis

**Target guidance:** `skills/visual-illustrator`, `skills/show-me`, and
`skills/artifact-audit`. The publisher contract remains unchanged; this RFC does
not authorize a `publish.sh` or `src/` implementation change.

---

## 1. Context & Problem Statement

### 1.1 The Mermaid Renderer Paradox (Issue #21)

The plugin's documentation and skills prescribe Mermaid as a useful visual
format. `artifact-audit` validates Mermaid syntax, but the publisher injects no
Mermaid runtime into an artifact. A published HTML page containing
`<pre class="mermaid">` or a raw ` ```mermaid ` fence therefore displays source
text instead of a diagram. This is a silent failure: the audit can pass, the
upload can succeed, and the reader still receives unrendered code.

Mermaid remains the right lightweight authoring format for inline chat and pure
Markdown documents. Published HTML needs a different delivery contract: the
diagram must already be rendered, sanitized, and self-contained when it leaves
the agent.

### 1.2 Layout Ergonomics & Cognitive Load (Issue #23)

Wide topologies can introduce `overflow-x: scroll` or `overflow-x: auto` in the
primary diagram card. A reader then loses the system-level relationship while
dragging left and right to inspect a single view.

> **User requirement:** การวาดไดอะแกรมแบบที่ต้องเลื่อนซ้ายขวาเพื่อให้เห็นเนื้อหาทั้งหมดไม่เหมาะสม เพราะไม่เห็นภาพรวม ย่อให้เล็กแบบไม่มี scroll แล้วมีปุ่มกดให้ดูรายละเอียดมากกว่า
>
> The overview must fit without horizontal scrolling, with a control for
> detail inspection.

---

## 2. Accepted Architecture

### 2.1 Cross-Vendor Review synthesis

The review compared runtime injection, hybrid fallback, and static delivery
against offline behavior, browser portability, security, accessibility, and
maintenance cost. The accepted result is:

> **Option 4 (Static Sanitized Inline SVG Delivery).**

Published HTML artifacts MUST contain clean inline SVG with a `viewBox`, a
responsive sizing contract, and no Mermaid runtime dependency. The SVG is the
rendered representation; Mermaid source is not a second hidden delivery path.

The earlier draft used the same static idea under the label “Option 1”. The
cross-vendor decision standardizes the final name as Option 4 so that the
accepted architecture is unambiguous in future reviews.

| Surface | Authoring format | Published representation | Runtime dependency |
| :--- | :--- | :--- | :--- |
| Inline chat | Mermaid, pseudocode, trees, or a small diff | The inline response itself | The chat renderer, when available |
| Pure Markdown | Mermaid fenced block when useful | Markdown/Mermaid | The consuming Markdown renderer |
| Published HTML overview | Sanitized semantic inline SVG | Static SVG in the HTML | None |
| Published HTML detail view | The same sanitized SVG in a viewport lightbox | `<dialog>` where available, with a safe fallback tier | Optional local JavaScript only |

This decision keeps Mermaid archetype and syntax guidance for chat and Markdown
while making static SVG the only rich-diagram delivery format for HTML artifacts.

### 2.2 Fit-first responsive behavior

Every published HTML diagram MUST use a primary overview container with:

- `max-width: 100%` and `overflow: hidden`;
- no horizontal scrollbar in the overview, including on narrow viewports;
- inline SVG sized with `width="100%"`, `height="auto"`,
  `preserveAspectRatio="xMidYMid meet"`, and a `viewBox="0 0 W H"`;
- `max-height: 480px` for the overview, with legible labels and stroke widths.

Detail inspection is progressive disclosure, not a substitute for the overview.
The detail viewport may pan or scroll inside its own bounded surface after the
reader activates **Viewport Lightbox / Expand Detail**.

### 2.3 Terminology

All guidance and UI labels use **Viewport Lightbox / Expand Detail**. The
previous full-display wording is retired because the component is a bounded
inspection viewport, not a promise to replace the browser's entire display or
browser chrome.

The standard trigger is:

`🔍 ขยายดูรายละเอียด (Expand / View Detail)`

---

## 3. SVG Security Allowlist and Sanitization

Static does not mean trusted. Before an SVG is embedded in an artifact, the
generator and audit gate MUST apply the following allowlist and reject anything
outside it.

### 3.1 Allowed shape vocabulary

The safe baseline is `svg`, `g`, `path`, `rect`, `circle`, `ellipse`, `line`,
`polyline`, `polygon`, `text`, `tspan`, `title`, `desc`, `defs`,
`linearGradient`, `radialGradient`, `stop`, `marker`, and `clipPath`, together
with presentation attributes needed for those shapes. CSS MUST remain local to
the artifact and cannot load a remote resource.

Every diagram's reusable resources MUST use a per-diagram namespace. IDs MUST
use the `id="diag1-..."` pattern (for example, `id="diag-auth-grad1"`,
`id="diag-auth-marker1"`, and `id="diag-auth-clip1"`) and MUST be unique within
the complete HTML document. A
reference such as `url(#diag-auth-grad1)` is allowed only when the target is a
local resource in the same SVG.

### 3.2 Mandatory rejects

The following are never allowed in a published inline SVG:

- `<script>` or any executable content;
- inline event handlers such as `onclick`, `onload`, or any attribute beginning
  with `on`;
- `javascript:` URLs or any other active URL scheme;
- `<foreignObject>`;
- external `url()` references, external images, stylesheets, fonts, or other
  assets;
- duplicate or unnamespaced IDs, including collisions introduced by copying a
  diagram into its detail viewport.

The lightbox's optional JavaScript belongs to the surrounding HTML component,
not inside the SVG. Moving the one sanitized SVG node into the detail viewport
avoids cloning its IDs and preserves the namespace invariant.

---

## 4. Viewport Capability Tiers

The overview contract applies in every tier. The tiers describe how a reader
reaches detail inspection when browser capabilities differ.

| Tier | Capability | Required behavior | Degradation boundary |
| :--- | :--- | :--- | :--- |
| **Tier A** | Native `<dialog>` + local JavaScript | Open with `showModal()`, expose a backdrop, provide Zoom In (`+`), Zoom Out (`-`), Reset (`↺`), close on `Esc` and backdrop click, trap focus, and restore focus to the trigger. | Detail controls may be unavailable only after a capability failure; the fit-first overview remains usable. |
| **Tier B** | Iframe viewport | Open a same-document or locally generated iframe viewport with the sanitized SVG and bounded pan/zoom controls. Keep the primary page free of horizontal scrolling. | The iframe is a detail surface, never a reason to widen the overview card. |
| **Tier C** | No JavaScript / static fallback | Keep the sanitized inline SVG at 100% fit with accessible title/description text and a visible detail affordance or explanatory fallback. | No runtime controls are promised; static fit and SVG accessibility remain mandatory. |

Tier A is the preferred implementation. Tier B and Tier C are compatibility
paths, not permission to ship raw Mermaid or unsafe SVG.

---

## 5. Audit Gate Matrix

`artifact-audit` evaluates the delivery contract before publication. The
severity is fixed so that a visually plausible but unsafe or unusable artifact
cannot pass by accident.

| Check | Candidate condition | Verdict | Required action |
| :--- | :--- | :---: | :--- |
| Raw Mermaid in HTML | `.html` contains `<pre class="mermaid">` or a raw ` ```mermaid ` fence without a static rendered SVG representation | 🔴 BLOCK | Render and sanitize inline SVG; retain Mermaid only in chat/Markdown. |
| Primary overview scroll | A diagram card uses `overflow-x: scroll` or `overflow-x: auto` for its primary overview | 🔴 BLOCK | Apply `max-width: 100%` and `overflow: hidden`; move detail navigation into the viewport. |
| SVG security and ID hygiene | SVG contains script, `on*` handlers, `javascript:` URLs, `<foreignObject>`, external `url()`/assets, duplicate IDs, or IDs without a diagram namespace | 🔴 BLOCK | Remove the unsafe content and regenerate unique local IDs. |
| Complex diagram detail | Diagram has more than 12 nodes and no Expand Detail/lightbox trigger | 🟡 WARN | Add the accessible Viewport Lightbox component or document why the diagram is intentionally simple. |
| Fit-first and accessible detail | Overview fits 100% of its container, is readable, and provides an accessible native `<dialog>` lightbox when supported | 🟢 PASS | Continue to the remaining audit dimensions. |
| Mermaid in chat/Markdown | Mermaid follows the existing quoting, orientation, and nesting rules in inline chat or pure Markdown | 🟢 PASS | Keep Mermaid; do not convert small conversational diagrams solely for this RFC. |

No BLOCK may be published. A WARN requires the normal approval policy for the
artifact's visibility, while a PASS still does not replace the other audit
dimensions or owner release approval.

---

## 6. Component and Skill Impact

### 6.1 `skills/visual-illustrator/SKILL.md`

- Add the fit-first responsive container and static SVG rules.
- Supply a copy-pasteable accessible `<dialog>` component with local JavaScript,
  focus restoration, focus trapping, keyboard controls, and the standard
  trigger label.
- Require namespaced SVG resource IDs and the security rejects in Section 3.
- Preserve Mermaid archetypes for inline chat and pure Markdown.

### 6.2 `skills/show-me/SKILL.md`

- Make sanitized inline SVG plus Viewport Lightbox / Expand Detail the rich
  diagram contract for published HTML.
- Keep Mermaid, pseudocode, diffs, and file trees as lightweight inline-chat
  responses when a standalone artifact is unnecessary.

### 6.3 `skills/artifact-audit/SKILL.md`

- Add the raw-Mermaid, primary-scroll, SVG-security, and ID-collision BLOCKs.
- Add the complex-diagram lightbox WARN and fit-first accessible-lightbox PASS.
- Route each finding to the responsible skill before publication.

### 6.4 Publisher and source code

No `publish.sh` or `src/` change is part of this decision. The skills generate
the accepted representation before the existing publisher receives the HTML.
Publisher behavior remains subject to its independent security and artifact
integrity tests.

---

## 7. Acceptance Criteria

An implementation is complete when:

1. The RFC and all three skills name Option 4 and the Viewport Lightbox / Expand
   Detail terminology consistently.
2. Published HTML guidance requires static sanitized inline SVG and rejects raw
   Mermaid, primary horizontal scrolling, unsafe SVG content, and ID collisions.
3. The responsive SVG contract and capability tiers are documented, including
   the no-JavaScript fit-first fallback.
4. The audit matrix, verdict rules, and remediation routes agree on BLOCK,
   WARN, and PASS severity.
5. Existing Mermaid guidance for inline chat and pure Markdown remains intact.
6. YAML frontmatter for every changed `SKILL.md` retains `name` and
   `description`, with each description at or below 1024 characters.

## 8. Resolved Review Questions

1. **Inline SVG vs Mermaid runtime injection:** choose Option 4 static sanitized
   inline SVG for published HTML; do not add a runtime or CDN dependency.
2. **Ergonomic component:** use native HTML5 `<dialog>` with local Vanilla JS
   as Tier A, with Tier B and Tier C fallbacks.
3. **Missing detail trigger:** a complex diagram without a trigger is a WARN;
   unsafe markup or a broken fit-first overview is a BLOCK.
