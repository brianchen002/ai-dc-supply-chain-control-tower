# SOP-02: Partial Fulfillment & Split Shipments

**Owner:** Inventory Ops · **Last reviewed:** 2026-06 · **Applies to:** all DCs

## Purpose

Define when to ship what is available versus hold for a complete order, and how to execute a split shipment without breaking customer promises or freight budgets.

## Trigger conditions

A PARTIAL_FULFILLMENT exception is raised when ATP at the assigned warehouse covers part but not all of an order line, or some lines of a multi-line order are fully available while others are not.

## Decision criteria

- **Platinum tier:** default to split shipment — ship available units/lines immediately, expedite the remainder when it lands. Meridian absorbs the second-leg freight.
- **Gold tier:** split if the unavailable remainder is expected within 3 business days OR the available portion is at least 60% of order value. Otherwise consult the customer.
- **Standard tier:** hold for complete shipment unless the customer explicitly requests a split; a second parcel is offered at customer expense for orders under $500 total.
- Never split a line below a shippable unit (e.g., do not break case packs).
- If the remainder has no confirmed recovery date (no inbound PO), treat the remainder as a stockout and apply SOP-01.

## Procedure

1. Quantify the split: available now vs. remainder, with recovery ETA from inbound POs or transfers.
2. Apply the tier rules above and record the decision on the exception.
3. If splitting: release the available portion to picking, create a backorder line for the remainder with its ETA, and confirm the plan to the customer in the same business day.
4. If holding: set a follow-up on the recovery ETA and re-check ATP daily.
5. Resolve the exception once the plan is executed and the customer is informed.

## Escalation

Escalate to the Fulfillment Ops manager when a split would trigger more than two shipments for one order, when second-leg freight exceeds $200, or when a Platinum remainder has no recovery date within 5 business days.

## Related SLAs

High-severity partials (Platinum): first action within 8 hours. Medium: within 24 hours. Split confirmations must reach the customer the same business day the decision is made.
