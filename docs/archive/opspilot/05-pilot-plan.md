# Pilot Plan & User Scenarios — OpsPilot

## 1. User scenarios (how the product is actually used)

**Scenario A — Morning triage (Maya, Fulfillment Ops Manager).**
7:45 AM. Maya opens the Dashboard: 56 open orders, 30 past promise, 75 open
exceptions, ~$120k value at risk. She clicks *Generate today's digest*. It
names the three costliest risks with order IDs, flags that one carrier holds
most open transit delays and that 13 unblocked SLA-risk orders cluster at
WH-ATL — a picking-capacity signal, not an inventory problem. She moves two
pickers to WH-ATL and posts the three per-team focus items in the ops channel.
*Elapsed: 6 minutes (previously ~45).*

**Scenario B — Resolving a stockout (Derek, Order Management).**
Derek opens the top critical exception: `STOCKOUT — ELC-6442 blocks ORD-10376`.
The AI recommendation shows: transfer from WH-DFW (166 ATP vs 2 required,
+1 transit day), or hold for the inbound PO landing Friday — and reminds him
the customer must be notified before the promise lapses (SOP-01). He books the
transfer, notes it on the exception, resolves. *No senior coordinator involved.*

**Scenario C — Policy question (new hire, week 2).**
"Can I split-ship a partial order for a Gold customer?" The Copilot answers
from SOP-02: yes, if the remainder recovers within 3 business days or ≥60% of
value ships now — with the section cited. *Zero interruptions; answer is
policy, not folklore.*

## 2. Pilot scope

| | |
|---|---|
| **Site** | WH-ATL (highest exception volume) |
| **Users** | 4 — ops manager, 2 coordinators, 1 shift lead |
| **Duration** | 4 weeks + 1 week phase-0 replay |
| **Systems** | Read-only OMS/WMS extracts refreshed every 15 min; no write-back |
| **AI mode** | Live (budget-capped); offline fallback always on |

**Phase 0 (week 0) — historical replay.** Run detection over the past 60 days
of real data; ops manager audits precision/recall of every exception type
against what the team actually experienced. **Gate: ≥90% precision** on
blocking types before any operator sees the tool. This is the main defense
against "synthetic data flattered the engine."

**Phase 1 (weeks 1–2) — shadow mode.** Team works normally; OpsPilot runs in
parallel. Daily 15-min review: would the queue order and recommendations have
been right? Tune weights/severity per the change process in decision rules §6.

**Phase 2 (weeks 3–4) — primary mode.** Queue becomes the default work order;
exceptions worked from the Exception Center; recommendation accept/edit/reject
instrumented per use.

## 3. Success criteria

Go/no-go reviewed with the VP Ops sponsor at week 4:

| Metric | Baseline | Target | Instrument |
|---|---|---|---|
| Median exception resolution time | ~26h | –30% | exception timestamps |
| On-time ship rate (WH-ATL) | 87% | +4 pts | shipments vs promises |
| Morning triage time | ~45 min | ≤10 min | time-motion, self-report |
| Senior-staff process interruptions | ~12/day | –50% | interruption log |
| Recommendation acceptance | — | ≥60% accepted/edited | in-app instrumentation |
| Copilot answer usefulness | — | ≥70% thumbs-up | in-app rating |

Secondary watch: expedited-freight spend (should fall as exceptions surface
earlier), queue-deviation rate (cherry-picking signal).

## 4. Risks & mitigations

| Risk | L×I | Mitigation |
|---|---|---|
| Detection precision below gate on real data | M×H | Phase-0 replay + per-type thresholds tuning before exposure |
| Operators distrust/ignore the queue | M×H | Score transparency; shadow-mode co-design; deviation metric reviewed weekly, not punished |
| LLM recommendation contradicts policy | L×H | SOP-grounded prompts; acceptance instrumentation; offline mode as deterministic floor |
| Customer data in prompts (privacy) | M×M | DPA review pre-pilot; field allow-list in context builder; no PII beyond company name needed |
| 15-min data staleness causes wrong ATP | M×M | Staleness timestamp shown in UI; event-driven ingestion is roadmap R1 |
| Pilot team regresses to spreadsheets under load | M×M | Ops manager owns the ritual (digest posted daily); tool must save time in week 1 or we fix friction immediately |

## 5. Open questions

1. Does Finance Ops join the pilot, or do PAYMENT_HOLD exceptions route to
   their existing queue via email bridge?
2. Threshold for auto-resolving duplicates (R2) — is 24h-hold-then-cancel
   acceptable to sales?
3. Who owns SOP updates surfaced by unanswered Copilot questions — ops
   enablement or each owning team?
4. Post-pilot: WH-DFW and WH-RNO rollout sequencing and whether shift leads
   get scoped write-back (R6) first.
