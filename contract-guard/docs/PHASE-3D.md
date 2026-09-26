# ContractGuard — Phase 3D: What-If / Pre-Change Simulation

## Overview

In **Phase 3D**, ContractGuard enables developers and agents to simulate hypothetical API changes in memory before making actual modifications:

> **"What happens to downstream consumers if I make this API change?"**

Crucially, **What-If is a pure analysis / simulation**.

---

## 1. Absolute Non-Mutation Invariant

The What-If simulation guarantees zero side-effects:
- **No file modifications**: Producer and consumer contracts, source files, and tests remain untouched.
- **No Git state alterations**: No commits, branch creations, stashes, or index modifications.
- **In-Memory Transformation**: The OpenAPI document is parsed, deeply copied into memory, modified according to the hypothetical change, and fed into the standard deterministic `Comparator` engine.

---

## 2. Supported Simulated Changes

| Change Kind | Description | Example | Predicted Impact |
|---|---|---|---|
| `field_renamed` | Rename existing response or request property | `paymentAmount -> totalAmount` | `BREAKING` (MAJOR) |
| `field_removed` | Remove existing property | Remove `paymentAmount` | `BREAKING` (MAJOR) |
| `endpoint_removed` | Remove entire path or HTTP method | Remove `/api/payments/{id}` | `BREAKING` (MAJOR) |
| `field_optional_added` | Add new optional field | Add `bonusNote: {type: string}` | `COMPATIBLE` (MINOR) |
| `field_required_added` | Add new required field | Add `requiredField: {type: string}` | `BREAKING` (MAJOR) |

---

## 3. CLI Usage

```bash
# Simulate breaking field rename
contract-guard what-if . \
  --producer payment-service \
  --endpoint "/api/payments/{id}" \
  --field paymentAmount \
  --new-field totalAmount \
  --change-kind field_renamed

# Simulate compatible addition in JSON format
contract-guard what-if . \
  --producer payment-service \
  --endpoint "/api/payments/{id}" \
  --field bonusField \
  --change-kind field_optional_added \
  --format json
```

### CLI Terminal Output Example

```text
======================================================================
CONTRACTGUARD WHAT-IF SIMULATION [SIMULATED / NOT APPLIED]
======================================================================
Producer:       payment-service
Proposed:       paymentAmount -> totalAmount
Endpoint:       /api/payments/{id}
Change Kind:    field_renamed
Classification: BREAKING
Release Status: BLOCKED
SemVer Impact:  1.4.0 -> 2.0.0 (MAJOR)

BLAST RADIUS (PREDICTED)
  Direct Consumers:        3
  Affected Consumers:      3
  Contract-Only Consumers: 2
  Confirmed Source Files:  1
  Confirmed Test Files:    1
  Likely Source Files:     1
  Transitive Consumers:    0

REQUIRED REPAIRS IF APPLIED
  - Update consumer contract: rename 'paymentAmount' to 'totalAmount'
  - Update affected consumer DTO/model mapping if present
  - Update source references if present
  - Update affected tests if present
  - Run consumer tests
  - Verify with ContractGuard before releasing
======================================================================
```

---

## 4. MCP Integration

IBM Bob can invoke pre-change simulation through the enriched `get_blast_radius` tool:

```json
{
  "name": "get_blast_radius",
  "arguments": {
    "workspace_root": "/workspace",
    "producer": "payment-service",
    "change_kind": "field_renamed",
    "endpoint": "/api/payments/{id}",
    "field": "paymentAmount",
    "new_value": "totalAmount"
  }
}
```

The response returns a structured simulation object including `"simulated": true`, predicted classification, affected consumers list, blast radius breakdown, and required repairs.
