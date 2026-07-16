# SOP-05: Carrier Delays & Delivery SLA Recovery

**Owner:** Logistics · **Last reviewed:** 2026-06 · **Applies to:** all outbound shipments

## Purpose

Manage shipments that miss promised delivery dates: recover the individual shipment, keep the customer informed, and detect systemic carrier problems early.

## Trigger conditions

A CARRIER_DELAY exception is raised when an in-transit shipment passes its promised delivery date without a delivery scan. Severity: critical for Platinum shipments more than 24 hours late; high for any shipment more than 48 hours late or any Platinum shipment; medium otherwise.

## Decision criteria

- **No scan for 24+ hours:** treat as potentially lost; open a carrier trace immediately rather than waiting.
- **Customer communication:** proactive notification is mandatory once a shipment is 24 hours late (Platinum: at first detection). Include a realistic revised ETA — do not relay carrier estimates that have already been missed once.
- **Reship threshold:** if the trace has no confirmed location within 48 hours, reship from the nearest DC with expedited service and file the carrier claim in parallel. Do not make the customer wait for the claim to settle.
- **Systemic pattern:** if one carrier accounts for 50% or more of open delay exceptions in a week, Logistics initiates a carrier performance review and may shift volume to alternates for affected lanes.

## Procedure

1. Check the latest tracking scan and the delay duration.
2. Open a trace with the carrier if scans are stale by more than 24 hours.
3. Notify the customer per the communication rules above; log the contact on the exception.
4. At the 48-hour trace mark with no location: trigger reship per the threshold rule and file the claim.
5. Record the carrier, lane and root cause on the exception before resolving — this feeds the weekly carrier scorecard.

## Escalation

Escalate to the Logistics manager when: a Platinum shipment has no recovery path inside 24 hours, one order accumulates a second delay after reship, or claim value exceeds $2,500. The weekly carrier review escalates to Procurement when a carrier misses its lane SLA two weeks running.

## Related SLAs

Critical: first action within 4 hours. High: within 8 hours. Proactive customer notification: within 24 hours of the missed delivery promise, or immediately for Platinum.
