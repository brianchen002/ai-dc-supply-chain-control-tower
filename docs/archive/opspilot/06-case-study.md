# Case Study — OpsPilot: AI-Enabled Supply Chain Operations Copilot

> Portfolio write-up, formatted to drop into a personal-site project page.
> Live demo: `<your Streamlit Cloud URL>` · Code: `<your GitHub repo URL>`

---

## TL;DR

I designed and built an AI-assisted supply chain workflow for a (fictional)
3-warehouse B2B distributor — covering order intake, inventory checks,
fulfillment prioritization, exception management, and operational decision
support. I owned it end-to-end as a product exercise: PRD, workflow diagrams
and decision rules first; then a working prototype in **SQL + Python + LLM
workflows** that summarizes operational exceptions, retrieves process
guidance from SOPs, and generates recommended next actions.

**Stack:** Python · SQLite/SQL · Streamlit · Anthropic API (with a
deterministic offline fallback) · hand-rolled TF-IDF retrieval ·
6 product docs · 22 automated self-consistency checks.

---

## The problem

Mid-size distributors run fulfillment on spreadsheets and tribal knowledge.
Three failure modes repeat everywhere: pickers work orders in export order
(not urgency), exceptions like stockouts surface at the pick face when cheap
fixes are gone, and resolution knowledge lives in two senior coordinators'
heads. The interesting product question: **where does AI actually help, and
where should it stay out of the way?**

## My answer: rules where trust is needed, AI where compression is needed

The prototype splits the work deliberately:

- **Deterministic layer** — a transparent 0–100 priority score
  (40% SLA urgency, 25% customer tier, 20% value, 15% age) where every rank
  decomposes into auditable components; and an exception engine that detects
  8 exception types *from data state* (an exception exists only if the
  inventory/payment/carrier condition is really true).
- **AI layer** — three LLM workflows on top: a daily digest that turns ~75
  open exceptions into a morning briefing with systemic patterns ("one
  carrier holds 40% of open transit delays"); per-exception next-action
  recommendations grounded in live context (other-warehouse availability,
  inbound PO ETAs) and cited SOP policy; and a Q&A copilot over the SOP
  library so new hires stop interrupting senior staff.

## Product decisions I'd defend in a review

1. **Explainable scoring before AI.** Operators won't act on AI suggestions
   layered on a ranking they don't trust. The queue is a rule score with a
   visible breakdown; the LLM never decides rank.
2. **Detected, never hand-logged exceptions.** Detection re-derives from
   state, so the demo (and tests) can assert every stockout is a real ATP
   shortfall. No stale alert queue.
3. **Pluggable LLM with a deterministic fallback.** With an API key the app
   uses Claude; without one, the same context pipeline composes output from
   templates. Anyone can run the demo at zero cost, and the fallback doubles
   as the production degradation path.
4. **TF-IDF instead of a vector DB.** The corpus is ~40 SOP sections;
   classic retrieval is accurate at that scale with zero infrastructure. The
   retriever interface is the seam where embeddings slot in when the corpus
   grows. Right-sizing infra is a product decision.
5. **Recommend, don't execute.** Write-back (creating transfers, releasing
   holds) is roadmapped but gated on pilot trust evidence — ≥60%
   recommendation acceptance — because automation without audit is how ops
   tools get uninstalled.

## Process (what the docs show)

Requirements → specs → build, in that order: PRD with personas and
acceptance criteria; Mermaid workflow diagrams for the order lifecycle and
exception loop; a decision-rules document where every weight and threshold
matches `src/config.py` by convention (a test asserts the invariants); a
data & API spec covering the 8-table schema, proposed production
OMS/WMS/carrier integrations, and per-workflow LLM contracts with grounding
guardrails; and a 4-week pilot plan with a phase-0 historical replay gate
(≥90% detection precision on real data before any operator sees the tool).

## The synthetic data is part of the design

All data is generated (seeded, ~520 orders / 60 customers / 80 SKUs / 3 DCs)
and **internally consistent by construction**: the generator creates raw
operational state, and the same detection engine that would run against a
production OMS derives the exceptions. Patterns are planted for the AI to
find — a carrier causing most delays, a capacity bottleneck at one DC —
so the digest demonstrates analysis, not summarization theater. A 22-check
test suite asserts the self-consistency.

## What I'd do next

Event-driven ingestion to replace batch state (R1), auto-resolution for
low-risk exception types (R2), a carrier scorecard (R3), and instrumented
write-back once pilot acceptance data justifies it (R6) — prioritized by
RICE in the PRD.

---

*Meridian Supply Co. is fictional; all data is synthetically generated for
demonstration. Screenshots: dashboard with AI digest · fulfillment queue
with score breakdown · exception center with AI recommendation · ops copilot.*
