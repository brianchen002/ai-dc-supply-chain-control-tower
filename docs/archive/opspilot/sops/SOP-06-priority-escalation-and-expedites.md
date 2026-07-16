# SOP-06: Priority, Escalation & Expedited Freight

**Owner:** Fulfillment Ops · **Last reviewed:** 2026-06 · **Applies to:** all DCs

## Purpose

Define how the fulfillment queue is ordered, when a human may override it, and who approves expedited freight spend.

## Trigger conditions

Applies continuously to queue management, and whenever an operator proposes to jump an order, expedite freight, or bump capacity between accounts.

## Decision criteria

- **Queue order** follows the OpsPilot priority score: 40% SLA urgency, 25% customer tier, 20% order value, 15% order age. The score is advisory but is the default work order; deviations must be justified on the order record.
- **Customer tiers:** Platinum (strategic accounts, 1-business-day ship promise), Gold (2 days), Standard (3 days). Tier changes come from account management only — operators never re-tier a customer to move an order up.
- **Manual override:** allowed for documented reasons (medical/safety-critical use, contractual penalty exposure, service recovery after a Meridian error). The reason is logged with the operator's name.
- **Expedited freight approval:** up to $200 incremental cost — shift lead may approve; $200–$500 — Fulfillment Ops manager; above $500 — Director of Operations. Service recovery expedites after a Meridian error up to $300 are pre-authorized.
- **SLA-risk orders** with no blocking exception are picking-capacity problems: shift leads rebalance labor to the affected DC before approving overtime.

## Procedure

1. Work the queue top-down within your DC; do not cherry-pick easy orders below the top decile.
2. For an override or expedite: record the reason, get the approval level required by the spend, and note both on the order.
3. When SLA-risk exceptions cluster (10+ open at one DC), the shift lead reviews staffing and reports the capacity gap at the daily ops huddle.
4. Re-check the queue after any batch of resolutions — priority scores shift as promises age.

## Escalation

A Platinum order predicted to miss its promise even with expedited freight escalates to the Fulfillment Ops manager and the account manager together — the account team owns the customer conversation before the miss, not after.

## Related SLAs

Ship promises by tier: Platinum 1 business day, Gold 2, Standard 3 (from order placement). Exception first-action targets: critical 4h, high 8h, medium 24h, low 72h.
