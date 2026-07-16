# SOP-03: Address Validation Failures

**Owner:** Order Management · **Last reviewed:** 2026-05 · **Applies to:** all channels (web, EDI, phone)

## Purpose

Correct ship-to addresses that fail carrier validation so labels can be generated, without shipping to a wrong or unserviceable address.

## Trigger conditions

An ADDRESS_INVALID exception is raised when the carrier API rejects the ship-to address at label creation or pre-validation (unknown street, missing suite/unit, non-serviceable ZIP, PO box for freight, mismatched city/ZIP). Severity is high when the promised ship date is within 24 hours.

## Decision criteria

- If the validation service suggests a corrected address with high confidence (single candidate, same ZIP), apply the correction and note it on the order — no customer contact required.
- If multiple candidates exist, the correction changes the city or ZIP, or the order is EDI-sourced (address came from the customer's system), confirm with the customer before editing.
- Orders above $5,000 or Platinum tier: always confirm the corrected address with the customer contact on file, regardless of confidence.
- Never hand-edit an address to force it through validation without a documented basis.

## Procedure

1. Review the carrier rejection reason and the suggested corrections.
2. Apply the decision criteria; correct directly or contact the customer (phone first for same-day promises, email otherwise).
3. Re-run validation; regenerate the label.
4. For EDI customers, log the correction back to the account team so the master record gets fixed at the source.
5. Resolve the exception with the corrected address noted.

## Escalation

If the customer is unreachable for 2 business hours on an order due within 24 hours, escalate to the Order Management lead, who may authorize a documented best-candidate correction for Standard-tier parcels under $1,000. Freight shipments are never released on an unconfirmed address.

## Related SLAs

High severity: first action within 8 hours. Same-day-promise orders: customer contact attempts begin within 1 hour of the exception being raised.
