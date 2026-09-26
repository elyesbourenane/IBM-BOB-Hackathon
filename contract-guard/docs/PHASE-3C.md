# ContractGuard — Phase 3C: Change Passport / Unified Impact Report

## Overview

In **Phase 3C**, ContractGuard introduces the **Change Passport**: a single deterministic, machine-readable representation of an API change and everything ContractGuard knows about it.

The Change Passport answers:
> **"What exactly changed, what does it affect, what will it require, and what is the current release status?"**

It unifies information from:
1. **Semantic Change**: The exact endpoint, method, change kind, and old/new values.
2. **Blast Radius**: Direct, affected, and contract-only consumers, along with confirmed/likely source and test files.
3. **Dependency Graph**: Multi-service topology and direct/transitive relationships.
4. **Repair Mission**: Structured actions and acceptance criteria for IBM Bob.
5. **SemVer Recommendation**: Major/minor/patch bump based on contract differences.
6. **Release Verification**: Gate status (`READY` / `BLOCKED`), remaining actions, and failure details.

---

## 1. Deterministic Architecture

The Change Passport follows the core ContractGuard architectural rule:
> **"AI reasons. Deterministic checks decide. Bob executes. Deterministic verification proves."**

- **Composition Without Duplication**: `ChangePassport` composes existing deterministic models (`DiscoveryReport`, `RepairMission`, `DependencyGraph`, `ReleaseVerification`) without reimplementing comparator or graph logic.
- **Deterministic Passport ID**: The passport ID is derived from a SHA-256 hash of substantive change attributes (`producer:endpoint:kind:field:new_value:status:affected_count`), guaranteeing repeatability across runs.
- **Machine & Human Formats**: Available in JSON (`to_json()`), Markdown (`to_markdown()`), and terminal text (`render_text()`).

---

## 2. Change Passport Schema

```json
{
  "passport_id": "passport-payment-service-0e5e779d",
  "producer": "payment-service",
  "contract": "payment-service/docs/openapi.yaml",
  "change": {
    "endpoint": "GET /api/payments/{id}",
    "method": "GET",
    "kind": "field_renamed",
    "field": "paymentAmount",
    "new_field": "totalAmount",
    "old_value": "paymentAmount",
    "new_value": "totalAmount",
    "compatibility": "breaking",
    "reason": "Consumer expects the old field name; renaming it is equivalent to removal."
  },
  "impact": {
    "direct_consumers": 3,
    "affected_consumers": 3,
    "contract_only_consumers": 2,
    "confirmed_source_files": ["src/main/java/PaymentDto.java"],
    "confirmed_test_files": ["src/test/java/PaymentDtoTest.java"],
    "likely_source_files": ["src/main/java/PaymentClient.java"],
    "likely_test_files": [],
    "transitive_consumers": 0,
    "counts": {
      "direct_consumers": 3,
      "affected_consumers": 3,
      "contract_only_consumers": 2,
      "confirmed_source_files": 1,
      "confirmed_test_files": 1,
      "likely_source_files": 1,
      "likely_test_files": 0,
      "transitive_consumers": 0
    }
  },
  "release": {
    "semver": "MAJOR",
    "recommendation": "MAJOR",
    "from": "1.4.0",
    "to": "2.0.0",
    "is_breaking": true,
    "reason": "Detected 3 breaking API contract change(s)."
  },
  "release_status": "BLOCKED",
  "verification": {
    "status": "BLOCKED",
    "is_ready": false,
    "compatible_consumers": 0,
    "incompatible_consumers": 3,
    "breaking_findings": 3,
    "remaining_actions": [
      "Update order-service consumer contract (paymentAmount)",
      "Update payment-client consumer contract (paymentAmount)",
      "Update reporting-service consumer contract (paymentAmount)"
    ],
    "next_step": "repair_remaining_consumers"
  },
  "dependency_graph": {
    "total_nodes": 4,
    "total_edges": 3
  },
  "repair_mission": {
    "mission_id": "mission-payment-service-460ca4c3",
    "status": "BLOCKED",
    "required_actions": [ ... ],
    "acceptance_criteria": [ ... ]
  }
}
```

---

## 3. CLI Command

Generate the passport using the CLI:

```bash
# Terminal text output (default)
contract-guard passport .

# JSON output for agent / automation pipelines
contract-guard passport . --format json

# Markdown output for PR descriptions or release notes
contract-guard passport . --format markdown
```

**Exit Codes**:
- `0`: Release status is `READY` (all consumers compatible, test suite passed).
- `1`: Release status is `BLOCKED` (breaking changes detected or test failures).
