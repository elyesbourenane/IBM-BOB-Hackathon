# ContractGuard — Phase 3A: Structured Repair Mission

## Overview

In **Phase 3A**, ContractGuard advances from a Git-aware contract safety gate into an **agentic API change safety workflow**.

When a producer API introduces a breaking contract change, ContractGuard generates a deterministic, machine-readable **Repair Mission** tailored for **IBM Bob**.

### Core Principle

> **AI reasons. Deterministic checks decide. Bob executes. Deterministic verification proves.**

ContractGuard never executes automated source-code edits on its own. Bob remains responsible for execution, while ContractGuard provides exact, deterministic guidance and post-repair proof.

### Conceptual Workflow Evolution

**Before Phase 3A (Detection & Advisory Gate):**
```
ContractGuard: Detect -> Analyze -> Verify
```

**Phase 3A (Agentic Safety Workflow):**
```
ContractGuard:  Detect -> Analyze -> Create Repair Mission
Bob:            Read Mission -> Plan -> Edit -> Test
ContractGuard:  Verify -> READY/BLOCKED -> Evidence
```

The **Repair Mission** is:
- **Deterministic**: Pure rule evaluation; identical inputs yield identical missions and stable hashes.
- **Machine-Readable**: Standard JSON structure consumable via CLI or MCP.
- **Contract-Grounded**: Built directly from actual OpenAPI schema diffs.
- **Conservative on Code Impact**: Distinguishes **confirmed** evidence from **inferred/likely** impact and never invents source files.
- **Actionable for Bob**: Contains structured instructions and unambiguous acceptance criteria.

---

## 1. Division of Responsibilities

ContractGuard strictly enforces clear boundaries across its components:

| Responsibility | Deterministic ContractGuard | Mistral AI | IBM Bob |
|---|:---:|:---:|:---:|
| Contract parsing & AST comparison | **Authoritative** | ❌ Forbidden | ❌ |
| Breaking vs. Compatible decision | **Decides** | ❌ Cannot override | ❌ |
| Consumer discovery & dependency graph | **Authoritative** | ❌ | ❌ |
| Confirmed file impact (exact tokens) | **Authoritative Facts** | ❌ Cannot invent | ❌ |
| Likely file impact (call path heuristics) | Inferred | Inferred | ❌ |
| Semantic explanation & rationale | ❌ | **Explains** | ❌ |
| Advisory migration & repair guidance | ❌ | **Advisory** | ❌ |
| Authoritative Repair Mission generation | **Authoritative** | ❌ Does not generate | ❌ |
| Code editing & file modifications | ❌ Never edits code | ❌ Advisory only | **Executes** |
| Test suite execution | ❌ | ❌ | **Executes** |
| Release gate verdict (`READY`/`BLOCKED`) | **Decides** | ❌ Cannot override | ❌ |
| Reproducible release audit evidence | **Proves** | ❌ | ❌ |

- **Deterministic ContractGuard**: Parses contracts, evaluates compatibility rules, extracts semantic changes, computes confirmed blast radius, generates the Repair Mission, evaluates release gates, and hashes evidence.
- **Mistral AI**: Explains deterministic findings in natural language, suggests migration patterns, and provides developer rationale. Mistral *never* overrides deterministic verdicts and *never* generates the authoritative Repair Mission.
- **IBM Bob**: Consumes the structured findings and Repair Mission via MCP, plans code changes, edits consumer contracts/source/tests, executes test suites, and triggers deterministic verification.

---

## 2. "Confirmed" vs. "Likely" Impact

ContractGuard explicitly distinguishes between verified evidence and inferred context:

- **CONFIRMED Impact**: Deterministic evidence exists in the codebase. The exact affected schema token (e.g. `paymentAmount`, `getPaymentAmount`, `setPaymentAmount`) is found in the consumer source or test file.
- **LIKELY Impact**: Inferred from call-path heuristics (e.g. endpoint path segments like `/payments`). The file is relevant to the domain but does not directly reference the broken field token.

> **Invariant: No Invented Source Files**  
> If a consumer service has no confirmed source or test references (e.g. a contract-only consumer like `order-service` or `reporting-service`), `confirmed_source_files` and `confirmed_test_files` are strictly emitted as empty lists (`[]`). ContractGuard never hallucinates file paths.

---

## 3. The Repair Mission Structure

A **Repair Mission** encapsulates everything IBM Bob needs to safely resolve a contract break across a microservice fleet:

```json
{
  "mission_id": "mission-payment-service-1c4b7863",
  "title": "Repair breaking field rename in payment-service: paymentAmount -> totalAmount",
  "producer": "payment-service",
  "change": {
    "producer_service": "payment-service",
    "contract_path": "payment-service/docs/openapi.yaml",
    "endpoint": "GET /api/payments/{id}",
    "method": "GET",
    "change_kind": "field_renamed",
    "field": "paymentAmount",
    "old_value": "paymentAmount",
    "new_value": "totalAmount",
    "compatibility": "breaking",
    "reason": "Consumer expects the old field name; renaming it is equivalent to removal."
  },
  "severity": "breaking",
  "semver": {
    "bump": "major",
    "current_version": "1.4.0",
    "recommended_version": "2.0.0",
    "reason": "Detected 3 breaking API contract change(s)."
  },
  "status": "BLOCKED",
  "affected_consumers": [
    {
      "service": "payment-client",
      "contract": "contracts/payment-service.yaml",
      "affected_endpoints": ["GET /api/payments/{id}"],
      "affected_fields": ["paymentAmount"],
      "confirmed_source_files": [
        "src/main/java/com/example/paymentclient/model/PaymentResponse.java"
      ],
      "confirmed_test_files": [
        "src/test/java/com/example/paymentclient/client/PaymentClientTest.java"
      ]
    },
    {
      "service": "order-service",
      "contract": "contracts/payment-service.yaml",
      "affected_endpoints": ["GET /api/payments/{id}"],
      "affected_fields": ["paymentAmount"],
      "confirmed_source_files": [],
      "confirmed_test_files": []
    },
    {
      "service": "reporting-service",
      "contract": "contracts/payment-service.yaml",
      "affected_endpoints": ["GET /api/payments/{id}"],
      "affected_fields": ["paymentAmount"],
      "confirmed_source_files": [],
      "confirmed_test_files": []
    }
  ],
  "required_actions": [
    "Update consumer contract",
    "Update affected DTO/model mapping if present",
    "Update source references if present",
    "Update affected tests if present",
    "Run consumer tests",
    "Re-run ContractGuard verification"
  ],
  "acceptance_criteria": [
    "All discovered consumer contracts compatible",
    "No breaking findings remain",
    "Affected tests pass when available",
    "ContractGuard verification returns READY"
  ]
}
```

---

## 4. Key Invariants & Rules

1. **Deterministic Mission ID**:
   The `mission_id` is derived deterministically using a SHA-256 hash of canonical change metadata (`f"{producer}:{endpoint}:{change_kind}:{field}:{new_value}"`). It is stable across runs and never uses random UUIDs.

2. **No Invented Source Files**:
   Confirmed files are populated strictly via deterministic AST and token matching. Consumers lacking code matches retain empty lists.

3. **Deterministic Acceptance Criteria**:
   Bob's acceptance criteria are strictly defined:
   - All discovered consumer contracts compatible
   - No breaking findings remain
   - Affected tests pass when available
   - ContractGuard verification returns READY

4. **SemVer vs. Verdict Independence**:
   - **SemVer** reflects the intrinsic nature of the producer API change (`paymentAmount` → `totalAmount` is a breaking schema change requiring `MAJOR`).
   - **Verdict** reflects discovered consumer compatibility (`BLOCKED` before repair, `READY` after repair).
   - After consumer repair, the SemVer recommendation remains:
     ```
     1.4.0 -> 2.0.0 (MAJOR)
     Reason: Producer contract contains a breaking change, but all discovered consumers are compatible.
     ```

---

## 5. Artifact Consistency & Commands

ContractGuard generates specific, well-defined artifacts depending on the command executed:

| Artifact Name | Generating Command / Tool | Format | Purpose |
|---|---|---|---|
| `contractguard-evidence.json` | `contract-guard evidence` or MCP `verify_release_safety` | JSON | Machine-readable audit evidence with SHA-256 hash |
| `contractguard-report.md` | `contract-guard evidence` or MCP `verify_release_safety` | Markdown | Human-readable audit evidence report |
| `contractguard-pr.md` | `contract-guard pr --output <file>` | Markdown | PR-ready comment with verdict, SemVer, and blast radius |
| `contractguard-mission.md` | `contract-guard mission --format markdown --output <file>` | Markdown | Structured repair mission report for Bob / tickets |

---

## 6. CLI: `contract-guard mission`

Generate a repair mission directly from the command line:

```bash
# Terminal text output (default)
contract-guard mission .

# JSON format for agent pipelines
contract-guard mission . --format json

# PR/Issue markdown format
contract-guard mission . --format markdown --output contractguard-mission.md

# Filter by specific producer service
contract-guard mission . --producer payment-service
```

### Exit Codes

- `0 = READY`: All discovered consumer contracts are compatible with the proposed producer change.
- `1 = BLOCKED`: One or more discovered consumers are incompatible with the proposed producer change.
- `2 = ERROR`: Git, configuration, environment, or analysis error.

---

## 7. MCP Tools (8 Available)

Phase 3A exposes 8 MCP tools over standard JSON-RPC 2.0:

| Tool | Parameters | Description |
|---|---|---|
| `compare_contracts` | `producer_path`, `consumer_path` | Pairwise comparison between two OpenAPI YAML files |
| `read_contractguard_config` | `config_path` | Parse consumer `contractguard.yaml` and resolve paths |
| `discover_and_check_consumers` | `workspace_root`, `[producer_filter]` | Workspace-wide consumer check |
| `get_blast_radius` | `workspace_root`, `[producer_filter]` | Deterministic blast radius and file scan |
| `analyze_contract_impact` | `workspace_root`, `[producer_filter]` | AI-assisted explanation & advisory repair suggestions |
| `verify_release_safety` | `workspace_root`, `[producer_service]`, `[test_status]`, `[output_dir]` | Gate verification & audit evidence |
| `analyze_git_change` | `workspace_root`, `[base_ref]`, `[producer_filter]`, `[current_version]` | Git-aware PR change analysis |
| **`get_repair_mission`** | **`workspace_root`**, **`[producer_filter]`** | **Phase 3A: Structured, machine-readable Repair Mission for IBM Bob** |

---

## 8. Bob Workflow Walkthrough

1. **Producer Change**:
   Developer modifies `payment-service/docs/openapi.yaml`, renaming `paymentAmount` to `totalAmount`.
2. **ContractGuard Detection**:
   ContractGuard identifies that 3 consumers (`payment-client`, `order-service`, `reporting-service`) depend on `paymentAmount`.
3. **Bob Requests Mission**:
   Bob invokes MCP tool `get_repair_mission({"workspace_root": "."})`.
4. **Mission Generation**:
   ContractGuard returns the structured `RepairMission` identifying the 3 affected consumers, confirmed source file `src/main/java/com/example/paymentclient/model/PaymentResponse.java`, and confirmed test file `src/test/java/com/example/paymentclient/client/PaymentClientTest.java`.
5. **Bob Execution**:
   Bob updates:
   - `order-service/contracts/payment-service.yaml`
   - `reporting-service/contracts/payment-service.yaml`
   - `payment-client/contracts/payment-service.yaml`
   - `payment-client/src/main/java/com/example/paymentclient/model/PaymentResponse.java`
   - `payment-client/src/test/java/com/example/paymentclient/client/PaymentClientTest.java`
6. **Bob Tests**:
   Bob runs the consumer test suites.
7. **Deterministic Verification**:
   Bob calls `verify_release_safety` or `analyze_git_change`.
   - Consumers checked: 3
   - Compatible: 3
   - Affected: 0
   - Verdict: `READY` (Exit code 0)
   - SemVer: `1.4.0 -> 2.0.0 (MAJOR)`

---

## 9. Scope Boundaries & Limitations

- **OpenAPI REST Only**: Operates on OpenAPI 3.0.x / 3.1.x specifications. AsyncAPI, GraphQL, and gRPC remain deferred.
- **Local Git CLI Dependency**: Uses the host Git CLI; direct cloud APIs (GitHub/GitLab REST) remain deferred.
- **Shared Workspace Layout**: Assumes co-located services or submodules with `contractguard.yaml` configs.
- **Contract-Guided Code Analysis**: Detects source and test impact driven by contract schema tokens; purely internal code refactors without OpenAPI contract modifications cannot be detected statically via schema diffs alone.
- **Autonomous Editing Deferred**: ContractGuard generates the structured mission; execution and code modification remain the responsibility of Bob. Full Java static analysis frameworks remain deferred.

---

## 10. Verification & Test Suite

Phase 3A is fully verified against an automated test suite:

- **Total Tests Passing**: 133
- **Failures**: 0
- **Warnings**: 0
