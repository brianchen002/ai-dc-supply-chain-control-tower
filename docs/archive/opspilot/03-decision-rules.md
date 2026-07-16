# Decision Rules — OpsPilot

The operational logic of the product, written to be auditable by a
non-engineer. **Code and doc are kept in sync deliberately:** every constant
below lives in `src/config.py`; changing one requires changing the other in
the same commit.

## 1. Principles

1. **Deterministic before probabilistic.** Ranking and detection are rules;
   the LLM only summarizes, retrieves, and recommends on top of them.
2. **Every automated judgment is explainable** — a score decomposes, an
   exception names its data condition, a recommendation cites its SOP.
3. **Severity reflects business exposure** (customer tier, dollars, time), not
   just event type.

## 2. Fulfillment priority scoring

`score = 100 × (0.40·SLA + 0.25·Tier + 0.20·Value + 0.15·Age)` — weights from
stakeholder trade-off sessions: SLA dominates because a broken promise is the
costliest failure; tier reflects contractual commitments; value proxies
revenue exposure; age prevents starvation of small old orders.

**Component definitions** (each normalized to 0–1):

| Component | Input | Mapping |
|---|---|---|
| SLA urgency (0.40) | hours to promised ship date | past due → 1.00 · ≤24h → 0.85 · ≤48h → 0.60 · ≤72h → 0.35 · else 0.15 |
| Customer tier (0.25) | contract tier | Platinum 1.00 · Gold 0.65 · Standard 0.35 |
| Order value (0.20) | order total USD | min(value / $8,000, 1.0) — cap ≈ p95 of order values |
| Order age (0.15) | days since placement | min(age / 7 days, 1.0) |

**Worked example** (from the live dataset): an order overdue by 141h for a
Platinum customer at $13,526, 6.9 days old →
40.0 + 25.0 + 20.0 + 14.7 = **99.7**.

**Rules of use** (SOP-06): queue order is the default work order; manual
overrides require a documented reason; operators never re-tier customers.
Bucketed (not continuous) SLA urgency is intentional — operators reason in
shifts and days, and buckets make two orders' ranks comparable at a glance.

## 3. Exception taxonomy: severity & routing

Eight types, each with a data-state trigger, severity logic reflecting
exposure, and one owning team.

| Type | Trigger (data condition) | Severity | Owner |
|---|---|---|---|
| STOCKOUT | open line qty > ATP, ATP ≤ 0 | Platinum or promise ≤24h → **critical**, else **high** | Inventory Ops |
| PARTIAL_FULFILLMENT | 0 < ATP < line qty | Platinum → **high**, else **medium** | Inventory Ops |
| ADDRESS_INVALID | carrier validation failed, unshipped | promise ≤24h → **high**, else **medium** | Order Management |
| PAYMENT_HOLD | payment pending verification, unshipped | >$5,000 or Platinum → **high**, else **medium** | Finance Ops |
| CARRIER_DELAY | in transit, past promised delivery, no scan | Platinum & >24h late → **critical** · Platinum or >48h → **high** · else **medium** | Logistics |
| SLA_RISK | unshipped, promise ≤24h or past, **no other blocker** | overdue & Platinum → **critical** · overdue → **high** · else **medium** | Fulfillment Ops |
| DAMAGED_INVENTORY | damaged qty > 0 at a DC | net sellable < reorder point → **high**, else **low** | Inventory Ops |
| DUPLICATE_ORDER | same customer + value, <30 min apart, open | >$8,000 → **high**, else **medium** | Order Management |

**First-action SLAs by severity:** critical **4h** · high **8h** · medium
**24h** · low **72h**.

**Suppression rule:** SLA_RISK is not raised for orders already carrying a
blocking exception — the root cause is the actionable signal; double-alerting
trains operators to ignore alerts.

**Blocking types** (order cannot ship until resolved): STOCKOUT,
PARTIAL_FULFILLMENT, ADDRESS_INVALID, PAYMENT_HOLD, DUPLICATE_ORDER.

## 4. Resolution decision ladders (per type)

Full procedures live in the SOPs; the ladders below are the decision spine
the AI recommender follows.

- **Stockout (SOP-01):** warehouse transfer → inbound-PO hold (if ETA beats
  promise + grace) → substitution with customer approval → backorder with
  proactive notification. Platinum re-routes require customer notification.
- **Partial (SOP-02):** Platinum → split by default, company pays second leg;
  Gold → split if remainder ≤3 business days out or ≥60% of value ships now;
  Standard → hold for complete unless customer requests split.
- **Address (SOP-03):** auto-apply only single high-confidence same-ZIP
  candidate; confirm with customer if multi-candidate, city/ZIP change, EDI
  source, >$5,000, or Platinum. Freight never releases on unconfirmed address.
- **Payment (SOP-04):** terms overage <15% & current AR → one-time override;
  card mismatch → new payment, never ship on failed verification; fraud screen
  → callback to number *on file*. 48h without customer response → void & notify.
- **Carrier delay (SOP-05):** stale scans >24h → open trace; 24h late →
  mandatory customer notification (Platinum: immediately); no location at 48h
  → reship expedited + claim in parallel.
- **Duplicate:** hold newer order → confirm intent → cancel or release within 24h.
- **Damaged:** quarantine → check reorder-point exposure → expedite/raise PO →
  claim; affected open orders handled as stockouts.
- **SLA risk (SOP-06):** confirm no blocker → work at queue position →
  expedite within approval limits; clusters (10+ at one DC) are a capacity
  signal for the shift lead, not individual order problems.

## 5. Escalation triggers (summary)

| Trigger | Escalates to |
|---|---|
| Platinum promise unrecoverable by any ladder path | Inventory Ops lead / Fulfillment Ops manager + account manager |
| >3 open orders blocked by one SKU | Inventory Ops lead |
| Expedited freight $200–500 / >$500 | Fulfillment Ops manager / Director of Ops |
| Credit override >15% of limit, or >$25k held per customer | Credit manager |
| Carrier ≥50% of open delays in a week | Carrier performance review (Logistics) |
| Claim value >$2,500 or second delay after reship | Logistics manager |

## 6. Change management

Weights and thresholds are product decisions, not code details. Changes go
through: proposal with expected queue impact (re-run the engine on current
data, diff the top 20) → ops manager sign-off → same-commit update of
`src/config.py` and this document. The prototype's `tests/test_engines.py`
asserts structural invariants (e.g. overdue Platinum outranks fresh Standard)
so a bad weight change fails CI.
