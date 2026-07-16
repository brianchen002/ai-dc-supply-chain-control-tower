# SOP-04: Payment Verification Holds

**Owner:** Finance Ops · **Last reviewed:** 2026-04 · **Applies to:** all channels

## Purpose

Clear or void orders held for payment verification quickly, balancing fraud/credit risk against fulfillment SLAs.

## Trigger conditions

A PAYMENT_HOLD exception is raised when the payment processor or credit check returns "pending verification": card verification mismatch, credit-limit review for terms customers, or a flagged first-time high-value order. Severity is high when order value exceeds $5,000 or the customer is Platinum tier.

## Decision criteria

- **Terms customers (invoice/net-30) over credit limit:** check outstanding AR. If the account is current and the overage is under 15% of the limit, Finance Ops may approve a one-time override. Larger overages require the credit manager.
- **Card verification mismatch:** request updated payment from the buyer; never ship on a failed verification.
- **First-order fraud screen:** verify business identity (domain, phone callback to the number on file — not the number on the order). Clear only on successful callback.
- Platinum-tier holds are worked first; their promise clock does not pause for payment review.

## Procedure

1. Identify the hold reason from the processor/credit system.
2. Apply the decision criteria; document evidence (AR status, callback result) on the exception.
3. Clear the hold and release the order to fulfillment, or void the order and notify the customer with the reason and next steps.
4. If verification is pending on a same-day promise, notify Fulfillment Ops so the pick slot is protected.
5. Resolve the exception with the outcome recorded.

## Escalation

Escalate to the credit manager when: the requested override exceeds 15% of credit limit, cumulative held value for one customer exceeds $25,000, or fraud indicators conflict (identity verifies but payment repeatedly fails). Suspected fraud is never cleared by a single approver.

## Related SLAs

High severity: first action within 8 hours. Medium: within 24 hours. A hold older than 48 hours without customer response converts to a void-and-notify by default.
