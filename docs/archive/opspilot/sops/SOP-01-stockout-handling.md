# SOP-01: Stockout Handling

**Owner:** Inventory Ops · **Last reviewed:** 2026-06 · **Applies to:** all DCs (WH-ATL, WH-DFW, WH-RNO)

## Purpose

Define how to resolve an order line that cannot be fulfilled because available-to-promise (ATP) inventory at the assigned warehouse is zero or negative, while protecting customer ship-date commitments.

## Trigger conditions

A STOCKOUT exception is raised when an open order line requires more units than ATP (on hand minus reserved minus damaged) at the order's assigned warehouse. Critical severity applies when the customer is Platinum tier or the promised ship date is within 24 hours.

## Decision criteria

Resolve stockouts in this order of preference:

1. **Warehouse transfer** — if another DC holds sufficient ATP, transfer or re-route fulfillment. Re-routing adds 1 transit day; acceptable for Gold/Standard if the promise date still holds, and for Platinum only with customer notification.
2. **Inbound PO within window** — if an inbound purchase order arrives before the promised ship date (plus 1 grace day for Standard tier), hold the line for the receipt and flag it to Fulfillment Ops.
3. **Substitution** — offer a functionally equivalent SKU of equal or higher grade at the original price. Requires customer approval; Order Management owns the outreach.
4. **Backorder with notification** — last resort. Customer must be notified before the original promise date, with a firm new date based on supplier lead time.

## Procedure

1. Confirm the shortfall: check ATP at the assigned DC and at the other two DCs.
2. Check inbound POs and their ETAs for the affected SKU.
3. Apply the decision criteria above; record the chosen path on the exception.
4. If transferring: create the transfer request and update the order's fulfilling warehouse.
5. If the promise date cannot be met, notify the customer before the date passes — never let a promise date lapse silently.
6. Resolve the exception with a note describing the resolution path.

## Escalation

Escalate to the Inventory Ops lead if: the stockout affects a Platinum customer and no resolution path holds the promise date, more than 3 open orders are blocked by the same SKU, or estimated recovery exceeds 5 business days. Escalations for order value above $10,000 also notify the Fulfillment Ops manager.

## Related SLAs

Critical stockout exceptions: first action within 4 hours. High severity: within 8 hours. Platinum promised ship dates must never slip without proactive customer contact.
