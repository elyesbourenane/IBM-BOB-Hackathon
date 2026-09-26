# ContractGuard — Phase 3F: Failure + Retry Scenario

## Overview

In **Phase 3F**, ContractGuard explicitly handles and validates the scenario where an AI agent's initial repair pass is incomplete or partial.

This capability is central to the IBM Bob hackathon story:
> **"ContractGuard is not merely a static one-shot linter. It is the deterministic verification referee in an active agentic repair loop."**

---

## 1. The Concrete Scenario

### Initial State
- **Producer**: `payment-service` renames `paymentAmount` to `totalAmount` in `openapi.yaml`.
- **Downstream Consumers**:
  1. `order-service` (expects `paymentAmount`)
  2. `payment-client` (expects `paymentAmount`, Java DTO & tests)
  3. `reporting-service` (expects `paymentAmount`)
- **Initial Verification**: `0/3 compatible`, `3 affected`, `status: BLOCKED`.

### Attempt 1: Partial Repair by Bob
Bob successfully updates:
- `order-service` contract
- `payment-client` contract and `PaymentDto.java`
- Intentionally overlooks or fails on `reporting-service`.

### Verification 1: Deterministic Rejection
ContractGuard independently inspects the workspace:
- `2/3 compatible` (`order-service`, `payment-client`)
- `1/3 incompatible` (`reporting-service`)
- `status: BLOCKED`
- **Remaining Action**: `"Update reporting-service consumer contract (paymentAmount)"`
- **Remaining Failure**:
  ```json
  {
    "consumer_service": "reporting-service",
    "consumer_contract": ".../reporting-service/contracts/payment-service.yaml",
    "endpoint": "GET /api/payments/{id}",
    "affected_field": "paymentAmount",
    "change_kind": "field_renamed",
    "detail": "Consumer expects 'paymentAmount' but producer now uses 'totalAmount'."
  }
  ```
- **Next Step**: `"repair_remaining_consumers"`

### Attempt 2: Targeted Retry by Bob
Armed with ContractGuard's exact, non-hallucinated failure feedback, Bob updates:
- `reporting-service/contracts/payment-service.yaml`

### Verification 2: Release Approved
ContractGuard verifies again:
- `3/3 compatible`
- `0 breaking findings`
- `status: READY`
- **Next Step**: `"release_or_commit"`
- Exit Code: `0`

---

## 2. Integration and Verification Guarantees

1. **No False Positives**: Already repaired consumers (`order-service`, `payment-client`) are recognized as compatible and not re-flagged.
2. **Precise Failure Isolation**: Only the remaining broken consumer (`reporting-service`) is reported in `remaining_actions` and `remaining_failures`.
3. **Deterministic State Derivation**: State is computed fresh from filesystem artifacts on every run, avoiding stale caches or persistent database drifts.
