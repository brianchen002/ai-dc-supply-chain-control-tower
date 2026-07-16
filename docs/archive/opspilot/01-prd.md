# PRD — OpsPilot: AI-Enabled Supply Chain Operations Copilot

| | |
|---|---|
| **Status** | Prototype shipped · pilot proposed |
| **Author** | Brian Chan (Product) |
| **Company** | Meridian Supply Co. (fictional B2B industrial supplies distributor, 3 DCs) |
| **Docs** | [Workflows](02-workflow-diagrams.md) · [Decision rules](03-decision-rules.md) · [Data & API spec](04-data-and-api-spec.md) · [Pilot plan](05-pilot-plan.md) |

---

## 1. Problem

Meridian's fulfillment team manages ~500 orders/month across three distribution
centers. The operational workflow — order intake, inventory checks, fulfillment
sequencing, exception handling — runs on spreadsheets, email threads, and tribal
knowledge. Three failure modes recur:

1. **Prioritization is ad hoc.** Pickers work orders in whatever sequence the
   morning export lists them. High-value Platinum orders miss 1-day ship promises
   while low-urgency orders ship early.
2. **Exceptions surface too late.** A stockout is typically discovered *at the
   pick face*, hours before a promise expires — when the cheap resolution paths
   (warehouse transfer, inbound-PO hold) are no longer viable.
3. **Process knowledge is concentrated.** Resolution steps live in six SOP
   documents nobody opens mid-shift and in two senior coordinators' heads.
   New hires take months to triage independently; senior staff get interrupted
   constantly.

## 2. Product hypothesis

If we (a) rank the fulfillment queue with a transparent priority score,
(b) detect exceptions from data state the moment they become true, and
(c) use an LLM to compress exception context and SOP policy into recommended
next actions, then operators resolve exceptions earlier and more consistently —
measured by exception resolution time, on-time ship rate, and senior-staff
interruption load.

## 3. Personas

**Maya — Fulfillment Operations Manager (primary).** Owns the daily plan for all
three DCs. Starts each day asking "what's on fire, and where do I put people?"
Today that answer takes ~45 minutes of spreadsheet triage. Needs: the morning
digest, the exception queue, value-at-risk framing.

**Derek — Order Management Coordinator (primary).** Works the exception queue:
addresses, payments, duplicates, customer callbacks. Two years in role but still
escalates policy edge cases ("can I override validation on an EDI freight
order?"). Needs: per-exception next actions, SOP answers in the flow of work.

**Priya — VP Operations (sponsor).** Approves the pilot. Cares about on-time
ship %, exception aging, and freight overspend. Needs: measurable success
criteria (see [pilot plan](05-pilot-plan.md)).

## 4. Goals / Non-goals

**Goals (prototype + pilot):**

- G1. Every open order carries an explainable priority score; the queue is the
  default work order at all DCs.
- G2. 100% of the eight defined exception types are detected from system state
  (no manual logging) and routed to an owning team.
- G3. For any exception, an operator gets grounded, SOP-cited recommended
  actions in under 10 seconds.
- G4. Process questions get answered from SOPs without interrupting a senior
  coordinator.

**Non-goals (explicitly out of scope for the prototype):**

- Automated *execution* of actions (creating transfer orders, releasing holds).
  The prototype recommends; humans act. Write-back is roadmap item R6.
- Demand forecasting or inventory replenishment optimization.
- Carrier rate shopping / TMS features.
- Multi-tenant or role-based access (pilot runs single-team).

## 5. User stories & acceptance criteria

**US-1 · Morning triage (Maya).** As an ops manager, I want a one-click daily
digest of open exceptions so that I can set team focus in minutes.
*Accepted when:* digest names the top risks with real exception/order IDs and
dollar values, surfaces systemic patterns (e.g. one carrier driving delays),
and recommends per-team focus with SOP citations — in one screen.

**US-2 · Work the queue (Derek/pickers).** As a coordinator, I want open orders
ranked by urgency so that I work the right order next without guessing.
*Accepted when:* every open order shows a 0–100 score; selecting any order
reveals the exact component breakdown (SLA, tier, value, age) summing to the
score; blocked orders are flagged with their blocking exception.

**US-3 · Resolve an exception (Derek).** As a coordinator, I want recommended
next actions for a specific exception so that I resolve it correctly the first
time. *Accepted when:* recommendations reference this exception's live context
(other-DC availability, inbound PO ETAs, shipment scans), only propose options
the data allows, cite the governing SOP section, and flag escalation triggers.

**US-4 · Ask process questions (any operator).** As an operator, I want to ask
policy questions in plain language so that I don't interrupt senior staff.
*Accepted when:* answers come only from the SOP corpus with section citations,
and the system says so explicitly when SOPs don't cover the question.

## 6. Functional scope (what shipped in the prototype)

| # | Capability | Where |
|---|-----------|-------|
| F1 | Order intake validation state (payment, address flags) | data model + detection |
| F2 | Inventory check / available-to-promise (ATP) per line | SQL + Queue page |
| F3 | Priority scoring engine, explainable breakdown | `src/priority_engine.py` |
| F4 | Exception detection from state — 8 types, severity + routing | `src/exception_engine.py` |
| F5 | AI daily digest (workflow 1) | Dashboard |
| F6 | AI next-action recommendations (workflow 2) | Exception Center |
| F7 | SOP retrieval Q&A (workflow 3) | Ops Copilot |
| F8 | Offline deterministic AI fallback | `src/llm/client.py` |

## 7. Key product decisions

1. **Explainable scoring before AI.** The queue is a weighted rule score, not a
   model. Operators must trust the ranking before they'll trust AI suggestions
   layered on it; every rank decomposes into 4 auditable components.
2. **Exceptions are detected, never hand-logged.** Detection runs off the same
   tables the OMS/WMS writes. If the data says ATP covers the line, there is no
   stockout exception — this keeps the queue honest and testable.
3. **LLM is pluggable with a deterministic fallback.** Same context pipeline
   either way; Claude composes in live mode, templates compose offline. This
   de-risks API cost/availability for the pilot and doubles as the degradation
   path in production.
4. **TF-IDF retrieval, not a vector DB.** The corpus is ~40 SOP sections;
   classic retrieval is accurate at this scale with zero added infrastructure.
   The retriever interface is the seam where embeddings slot in later (R4).
5. **Recommend, don't execute.** Until action-level audit and rollback exist,
   the system proposes and humans commit (R6 gates on pilot trust data).

## 8. Success metrics (pilot targets)

| Metric | Baseline (manual) | Target |
|---|---|---|
| Median exception resolution time | ~26h | **–30%** |
| On-time ship rate | 87% | **+4 pts** |
| Morning triage time (Maya) | ~45 min | **≤10 min** |
| Senior-staff process interruptions | ~12/day | **–50%** |
| AI recommendation acceptance rate | — | **≥60%** (instrumented) |

## 9. Prioritized roadmap (RICE)

| ID | Item | Reach | Impact | Confidence | Effort | RICE |
|----|------|------:|-------:|-----------:|-------:|-----:|
| R1 | Real-time OMS/WMS webhook ingestion (replace batch state) | 8 | 3 | 80% | 5 | 3.8 |
| R2 | Auto-resolution for low-risk types (duplicate cancel, address auto-fix) | 6 | 3 | 70% | 4 | 3.2 |
| R3 | Carrier scorecard & lane analytics module | 5 | 2 | 80% | 3 | 2.7 |
| R4 | Embedding-based retrieval + SOP coverage analytics | 6 | 2 | 60% | 3 | 2.4 |
| R5 | What-if ATP simulator (transfer/PO scenarios) | 4 | 2 | 60% | 3 | 1.6 |
| R6 | Write-back actions with audit trail (create transfers, release holds) | 7 | 3 | 50% | 8 | 1.3 |

Scale: Reach = affected users/workflows per month (relative 1–10), Impact 1–3,
Effort in person-weeks. R6 ranks last despite high impact — it's gated on pilot
trust evidence (acceptance rate ≥60%) and requires audit infrastructure.

## 10. Risks

| Risk | Mitigation |
|---|---|
| LLM proposes an action the data rules out | Grounding guardrails in prompts; context includes only viable alternatives; offline mode is fully deterministic |
| Operators ignore the queue and cherry-pick | Score transparency + SOP-06 makes queue order policy, not suggestion; measure deviation |
| SOPs drift from reality | Each SOP carries owner + review date; Copilot logs unanswered questions as gap signals |
| Synthetic data overstates detection accuracy | Pilot phase 0 replays 60 days of *real* historical exceptions before go-live (see pilot plan) |
