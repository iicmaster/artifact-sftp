---
name: artifact-curator
description: Executive Markdown Artifacts & Layout Architect - High-impact document structuring, callout alerts, comparison tables, and progressive disclosure.
---

# Artifact Curator Skill

Use this skill when you need to author, structure, polish, or transform documents, reports, proposals, specifications, and analyses into executive-grade Markdown and HTML artifacts.

---

## 1. Purpose & Core Philosophy

The purpose of `artifact-curator` is to transform dense, unstructured text into scannable, beautifully organized, high-impact executive documents. 

### Guiding Principles
- **Every pixel and character must earn its place on screen:** Remove visual clutter, verbose pleasantries, and redundant filler.
- **High scannability over exhaustive verbosity:** Enable senior leaders, engineering leads, and stakeholders to extract critical takeaways in seconds.
- **Information hierarchy through structural design:** Guide the reader's eye naturally from executive-level conclusions down to granular implementation specifications.
- **Deliberate typography and pacing:** Balance concise prose, visual callouts, structured comparison matrices, and syntax-highlighted code blocks.

---

## 2. Information Architecture Principles

### The 3-Second Rule (Executive Summary at the Top)
Busy executives and lead engineers will not read a 10-page document sequentially. Within **3 seconds** of opening the artifact, the reader must grasp:
1. **The Core Topic & Status:** What system, feature, or incident is being addressed, and what is its current status (e.g., `APPROVED`, `PROPOSED`, `RESOLVED`, `BLOCKED`).
2. **The Executive Takeaway (TL;DR):** The single most critical finding, decision, or metric.
3. **The Immediate Action / Next Step:** Who needs to do what next, or what decision is pending approval.

```markdown
# [Project / Incident / Feature Name]

> [!IMPORTANT]
> **Executive Verdict:** Migrating our core ingest pipeline to EventBridge reduces end-to-end latency by **68%** and cuts monthly cloud spend by **$4,200**. Approved for Sprint 24 rollout.

| Metric / Attribute | Baseline (Legacy) | Target (Proposed) | Impact / Delta | Status |
| :--- | :--- | :--- | :--- | :--- |
| **P99 Ingest Latency** | 1,420 ms | 450 ms | 🟢 -68.3% | Ready |
| **Monthly Compute** | $6,800 | $2,600 | 🟢 -$4,200/mo | Verified |
| **System Availability** | 99.90% | 99.99% | 🟢 +0.09% SLA | In Test |
```

---

### Progressive Disclosure Architecture

Organize all substantial artifacts into a 3-tier progressive disclosure model:

```
┌─────────────────────────────────────────────────────────────┐
│ Level 1: Executive Overview & Summary Matrix               │
│ • TL;DR, Status Badges, Bottom-Line Impact, Next Actions    │
├─────────────────────────────────────────────────────────────┤
│ Level 2: Core Analysis & Strategic Breakdowns               │
│ • Architecture decisions, Trade-off comparisons, Workflows  │
├─────────────────────────────────────────────────────────────┤
│ Level 3: Technical Implementation Details & Appendices       │
│ • Diffs, Schemas, API payloads, Configuration files, Logs    │
└─────────────────────────────────────────────────────────────┘
```

1. **Level 1 (Top 10-20%):** Immediate context, high-level impact tables, decision matrices, and critical callouts.
2. **Level 2 (Middle 50-60%):** Architectural diagrams, requirement tables, comparative trade-offs, and risk mitigations.
3. **Level 3 (Bottom 20-30%):** Exact diffs, code implementations, schema JSON/YAML definitions, rollback procedures, and appendices.

---

## 3. Visual Formatting Mastery

### Callout Alerts (`> [!ALERT]`)

Use GitHub-style alert callouts with deliberate intent to emphasize critical context.

| Callout Type | Semantic Meaning | Appropriate Use Case |
| :--- | :--- | :--- |
| `> [!NOTE]` | Informational Context | Background history, prerequisite knowledge, operational notes. |
| `> [!TIP]` | Optimization & Best Practice | Performance wins, developer shortcuts, recommended alternatives. |
| `> [!IMPORTANT]` | Crucial Requirement | Non-negotiable constraints, key decisions, mandatory prerequisite steps. |
| `> [!WARNING]` | Potential Risk / Breaking Change | Deprecations, compatibility caveats, non-fatal operational pitfalls. |
| `> [!CAUTION]` | Severe Danger / Security Risk | Data loss hazards, security vulnerabilities, irreversible production operations. |

#### Strict Callout Placement Rules
- **No Back-to-Back Callouts:** Never place two alert boxes immediately adjacent to one another. Separate them with contextual text, tables, or code.
- **No Over-Nesting:** Never place an alert callout inside another alert, inside a blockquote, or nested inside table cells.
- **Maximum Density:** Limit alert callouts to **1 or 2 per major section** (`##`). Overusing alerts causes cognitive blindness and diminishes their impact.

---

### Markdown Tables vs. Bullet Lists

Choosing the right format is critical for scanning speed.

```
Is the data multi-dimensional (2+ attributes per item)?
   ├─► YES: Use a Markdown Table.
   └─► NO:
        ├─► Sequential / Ordered steps? ──► Numbered List (1, 2, 3)
        └─► Homogeneous bullet points?  ──► Bullet List (- item)
```

#### When to Use Tables
- **Component & Feature Status:** Name, Owner, Target Date, Health Status, Notes.
- **Comparison & Trade-off Matrices:** Solution A vs. Solution B across Latency, Cost, Complexity, and Scalability.
- **API & Schema Definitions:** Field name, Data Type, Required/Optional, Default Value, Description.
- **RACI Matrices:** Task / Milestone, Responsible, Accountable, Consulted, Informed.

#### Table Formatting Standards
- Always include clear column headers with consistent text alignment:
  - Left-align text and descriptions: `:---`
  - Center-align status badges, versions, and codes: `:---:`
  - Right-align numbers, financial amounts, and percentages: `---:`
- Use semantic emoji indicators sparingly to enhance scanning: `🟢 Done`, `🟡 In Progress`, `🔴 Blocked`, `⚪ Deferred`.

---

### Carousels, Diff Blocks & Code Highlighting

#### 1. Diff Blocks
Use standard unified diff format to highlight modifications cleanly:

```diff
- const cacheTtl = 60 * 1000; // 1 minute (causes cache stampedes)
+ const cacheTtl = 15 * 60 * 1000; // 15 minutes with stale-while-revalidate
+ const jitter = Math.floor(Math.random() * 30000);
```

#### 2. Multi-Slide Carousels
Use 4-backtick carousel blocks for multi-step progressions, before/after UI mockups, or visual state comparisons:

````carousel
```markdown
### Phase 1: Ingestion
- Raw payloads written to S3 landing bucket.
- EventBridge triggers async validation lambda.
```
<!-- slide -->
```markdown
### Phase 2: Processing & Enrichment
- DynamoDB state machine tracks processing lifecycle.
- Dead-letter queue (DLQ) isolates malformed records.
```
<!-- slide -->
```markdown
### Phase 3: Materialization
- Analytical views refreshed in PostgreSQL read-replicas.
- Real-time websocket notification dispatched to client.
```
````

#### 3. Syntax Highlighting
Always specify the exact language identifier on fenced code blocks (`ts`, `js`, `json`, `yaml`, `bash`, `sql`, `mermaid`, etc.). Never leave code fences bare (```` ``` ````).

---

### Local File Linking Standards

When referencing project files, configurations, or specific code locations in artifacts, always use strict Markdown links with absolute file URIs:

- **Full File Link:** `[filename.ext](file:///absolute/path/to/filename.ext)`
- **Line Range Link:** [`service.ts:L45-L68`](file:///absolute/path/to/service.ts#L45-L68)
- **Symbol Link:** [`UserController.authenticate()`](file:///absolute/path/to/UserController.ts#L82-L115)

> [!NOTE]
> **Backtick Syntax Rule:** Keep backticks inside the link label brackets `[`label`](url)` or omit them `[label](url)`. Never wrap backticks around the link syntax (e.g., ``[`label`](url)`` or `[label](`url`)`).

---

## 4. Structure Archetypes & Production Templates

### Archetype 1: Architecture Decision Record (ADR)

```markdown
# ADR-042: Migration from REST Polling to SSE for Agent Event Streaming

| Metadata | Details |
| :--- | :--- |
| **Status** | 🟢 APPROVED |
| **Deciders** | Lead Architect, Backend Lead, Frontend Lead |
| **Date** | 2026-08-17 |
| **Supersedes** | ADR-018 (REST Polling Engine) |

---

## Executive Summary

> [!IMPORTANT]
> We will replace the current 2-second HTTP polling mechanism for agent transcript streaming with **Server-Sent Events (SSE)** over HTTP/2. This eliminates **85% of redundant network roundtrips** and cuts client memory consumption during long multi-turn sessions by **40%**.

---

## Context & Problem Statement

Under high concurrency (500+ active agents), the existing polling mechanism creates significant overhead:
- 30 requests per minute per active agent session, regardless of whether new tokens were generated.
- Server connection spikes and high database read contention on the session logs table.
- Mobile and weak-connection clients suffer from bursty UI updates and missed log streams.

---

## Decision Drivers & Evaluation Matrix

| Criterion (Weight) | Option 1: WebSocket | Option 2: SSE (Chosen) | Option 3: gRPC-Web |
| :--- | :---: | :---: | :---: |
| **Unidirectional Simplicity (High)** | 🟡 Bi-directional overkill | 🟢 Native HTTP stream | 🔴 High client complexity |
| **Infra & Proxy Compatibility (High)** | 🔴 Sticky proxy complexity | 🟢 Standard HTTP/2 stream | 🟡 Envoy proxy required |
| **Reconnection & Replay (Med)** | 🔴 Custom heartbeats | 🟢 Built-in `Last-Event-ID` | 🟡 Custom streaming logic |
| **P95 Latency Reduction (High)** | 🟢 45 ms | 🟢 48 ms | 🟢 42 ms |

---

## Decision Outcome & Invariants

**Chosen Option:** **Option 2: Server-Sent Events (SSE)**.

### Architectural Invariants:
1. All client streaming endpoints must expose `Content-Type: text/event-stream`.
2. Every emitted event must include an incremental `id:` field for transparent client-side replay.
3. Heartbeat comments (`: ping\n\n`) must be sent every 15 seconds to prevent intermediate proxy timeouts.

---

## Consequences & Mitigation

| Potential Consequence | Risk Level | Mitigation Strategy |
| :--- | :---: | :--- |
| Max 6 concurrent connections on HTTP/1.1 | 🔴 High | Enforce HTTP/2 on Cloudflare and upstream ALBs. |
| Client-side reconnection storms | 🟡 Medium | Implement exponential backoff with 20% jitter. |
```

---

### Archetype 2: Comprehensive Feature Specification / PRD

```markdown
# PRD: Global Multi-Branch Inventory Sync Engine

| Feature Attributes | Specifications |
| :--- | :--- |
| **Target Release** | v2.4.0 (Sprint 32) |
| **Product Manager** | John Doe ([@john](mailto:john@example.com)) |
| **Tech Lead** | Jane Smith ([@jane](mailto:jane@example.com)) |
| **Status** | 🟡 READY FOR IMPLEMENTATION |

---

## 1. Problem & User Value

Retail branch managers currently experience a **15-to-45 minute delay** in cross-branch stock visibility. This causes double-selling of high-demand items and delays stock rebalancing between regional warehouses.

> [!TIP]
> **Success Metric:** Reduce inter-branch stock consistency lag from 45 minutes to **< 500 milliseconds (P99)** across 120 store locations.

---

## 2. User Stories & Acceptance Criteria

| ID | User Story | Acceptance Criteria | Priority |
| :--- | :--- | :--- | :---: |
| **US-01** | As a store cashier, I want real-time stock lookup for nearby branches. | Stock counts update within 500ms of sale completion at any store. | P0 |
| **US-02** | As an inventory manager, I want automated stock reservation during transfers. | Inventory is locked in `TRANSFER_PENDING` state until destination scans receipt. | P0 |
| **US-03** | As a branch auditor, I want a ledger log of every stock mutation. | Immutable audit log record created with timestamp, actor ID, and delta. | P1 |

---

## 3. Data Contract & Payload Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "InventoryMutationEvent",
  "type": "object",
  "properties": {
    "eventId": { "type": "string", "format": "uuid" },
    "sku": { "type": "string", "pattern": "^SKU-[0-9]{8}$" },
    "branchId": { "type": "string" },
    "delta": { "type": "integer" },
    "reason": { "type": "string", "enum": ["SALE", "RETURN", "TRANSFER_OUT", "TRANSFER_IN", "ADJUSTMENT"] },
    "timestamp": { "type": "string", "format": "date-time" }
  },
  "required": ["eventId", "sku", "branchId", "delta", "reason", "timestamp"]
}
```

---

## 4. Rollout Strategy & Phasing

| Phase | Scope / Stores | Timeline | Success Gate |
| :--- | :--- | :--- | :--- |
| **Phase 1: Pilot** | 3 Flagship Stores (Bangkok) | Week 1 - 2 | 0 sync conflicts, P99 latency < 350ms |
| **Phase 2: Regional** | 25 Central Region Stores | Week 3 - 4 | Zero database deadlocks during peak flash sale |
| **Phase 3: Nationwide** | Full 120 Store Network | Week 5 | End-to-end audit parity verified |
```

---

### Archetype 3: Executive Meeting Summary & Action Items

```markdown
# Executive Sync: Q3 Core Platform Modernization

| Meeting Details | Information |
| :--- | :--- |
| **Date & Time** | 2026-08-17 14:00 - 15:00 ICT |
| **Chairperson** | VP of Engineering |
| **Attendees** | Architecture Guild, DevOps Lead, Security Lead |
| **Next Review** | 2026-08-24 14:00 ICT |

---

## Key Decisions Made

> [!IMPORTANT]
> **Summary Decision:** The migration of legacy MySQL clusters to Aurora Serverless v2 has been approved for execution in Phase 2. Security sign-off completed for AWS KMS multi-region customer managed keys.

1. **Approved:** Budget allocation for high-memory staging environments ($1,200/month).
2. **Postponed:** GraphQL Federation layer rollout deferred to Q4 to prioritize data layer reliability.
3. **Mandated:** Strict zero-trust mTLS required between internal microservices by end of sprint.

---

## Action Item Matrix (RACI)

| Action Item / Deliverable | Owner (R) | Approver (A) | Target Date | Status |
| :--- | :--- | :--- | :---: | :---: |
| **Benchmark Aurora v2 failover under 5k QPS** | `@devops-lead` | `@vp-eng` | 2026-08-20 | 🟡 In Progress |
| **Draft mTLS certificate rotation policy** | `@sec-engineer` | `@sec-lead` | 2026-08-22 | 🟢 Done |
| **Update Terraform modules for KMS key ring** | `@infra-team` | `@arch-lead` | 2026-08-23 | ⚪ Not Started |

---

## Open Issues & Parking Lot

- **Open Question:** Do we retain 30-day or 90-day cold storage backups for audit compliance? *(Awaiting Legal feedback)*.
- **Risk Item:** External webhook third-party partner has not yet enabled TLS 1.3.
```

---

### Archetype 4: Incident & Post-Mortem Report

```markdown
# INC-8921: Payment Gateway Webhook Ingestion Outage

| Incident Snapshot | Metrics |
| :--- | :--- |
| **Severity Level** | 🔴 SEV-1 (Critical Business Impact) |
| **Total Outage Duration** | 42 minutes (11:18 - 12:00 ICT) |
| **Affected Users / Transactions** | 1,420 checkout transactions |
| **Financial Impact (Delayed)** | ฿1,840,000 (100% recovered via webhook replay) |
| **Incident Commander** | Principal Site Reliability Engineer |

---

## 1. Executive Summary & Root Cause

> [!CAUTION]
> **Root Cause:** A database connection pool exhaustion in the `payment-webhook-service` caused by an unindexed query on `merchant_transactions` following migration `20260817_add_metadata_index.sql`. Inbound webhook workers timed out, filling the Redis worker queue to capacity.

---

## 2. Incident Timeline

| Time (ICT) | Event Description / Action Taken | Team / Actor |
| :--- | :--- | :--- |
| **11:18** | Automated PagerDuty alert: `payment-webhook-service` 5xx error rate > 5%. | CloudWatch Alert |
| **11:22** | SRE Team on-call acknowledges incident; triages database connection pool metrics. | SRE On-Call |
| **11:31** | Identified hung queries locking `merchant_transactions` table during checkout spikes. | Database Admin |
| **11:42** | Terminated blocking queries; applied hotfix index `idx_merchant_tx_status_created`. | DBA / Backend Lead |
| **11:50** | Service traffic normalized; initiated replay of 1,420 queued webhooks from DLQ. | SRE Team |
| **12:00** | All queued webhooks replayed successfully; zero data loss confirmed. Incident closed. | Incident Commander |

---

## 3. Corrective & Preventative Action Matrix

| Prevention Item | Category | Owner | Priority | Target Date |
| :--- | :--- | :--- | :---: | :---: |
| Add unindexed query guardrails in CI migration linter | Tooling | `@backend-infra` | P0 | 2026-08-21 |
| Configure RDS statement timeout to 5,000ms max | Database | `@dba-team` | P0 | 2026-08-18 |
| Implement automated DLQ redrive runbook script | Operations | `@sre-team` | P1 | 2026-08-25 |
| Conduct architectural review of payment isolation pool | Architecture | `@arch-guild` | P1 | 2026-08-28 |
```

---

## 5. Anti-Patterns to Avoid

```
❌ WALL OF TEXT                   ──► ✅ Structured sections with bold anchor headers
❌ BACK-TO-BACK ALERTS            ──► ✅ Single high-signal callout separated by data
❌ EXCESSIVE CARD NESTING         ──► ✅ Flat hierarchy with clear markdown tables
❌ UNTAGGED / DUMPED CODE         ──► ✅ Language-specified, trimmed, contextual snippets
❌ ARBITRARY BOLDING EVERYWHERE   ──► ✅ Bold reserved for key metrics, terms, and status
```

### Critical Sins of Document Layout
1. **The Unbroken Text Wall:** Paragraphs exceeding 4-5 lines without bold anchor words or bullet points.
2. **Alarmist Alert Spam:** Stacking 3 different callout boxes consecutively at the top of the page.
3. **Over-nested Bullet Hierarchies:** Creating 4-level deep bullet lists (`-`, `  -`, `    -`, `      -`). Flatten into tables.
4. **Untracked Code Bloat:** Pasting 200 lines of terminal output or raw JSON instead of relevant, highlighted 10-line snippets.
5. **Vague Relative Links:** Using broken relative paths like `[config](../config/app.json)` instead of standard absolute URIs.

---

## 6. Self-Verification Checklist

Before presenting or publishing any artifact, run through this quality gate:

- [ ] **3-Second Scannability:** Can an executive read the H1, the top callout, and the summary table to know the status within 3 seconds?
- [ ] **Progressive Disclosure:** Does the artifact flow logically from Executive Summary ➔ Strategic Details ➔ Code/Appendices?
- [ ] **Callout Discipline:** Are alerts (`> [!NOTE]`, `> [!IMPORTANT]`, etc.) spaced appropriately without back-to-back stacking?
- [ ] **Data Table Hygiene:** Are multi-dimensional attributes presented in formatted tables with clear column alignments?
- [ ] **Code Block Completeness:** Does every single code fence have an explicit language tag (`ts`, `json`, `diff`, `yaml`, etc.)?
- [ ] **Link Integrity:** Are all referenced files linked with proper absolute paths: `[file.ext](file:///path/to/file)`?
- [ ] **Thai Typography & Line-Height:** For Thai documents, is CSS `line-height` at least `1.5` (recommended `1.6`–`1.7`) to prevent vowel and tone mark overlap?
- [ ] **Tone & Focus:** Has all conversational AI filler ("Sure! Here is the document...") been stripped away?
