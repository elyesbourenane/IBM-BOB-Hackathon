# ContractGuard Phase 1 Technical Specification & Architecture Report

> **Core Axiom:**  
> *"AI reasons. Deterministic checks decide. Bob executes. Deterministic verification proves."*

---

## 1. Phase 1 Objective

Phase 1 consolidates the ContractGuard prototype into a solid, realistic, maintainable, demonstrable, and production-oriented core engine.

**Explicit Scope Exclusions (Deferred to Future Phases):**
- No database or ORM layer
- No web frontend or graphical UI
- No Git / GitHub / GitLab PR integration
- No API versioning engine
- No AsyncAPI or WebSocket protocol extensions
- No CI/CD pipeline automation plugins

**Core Target Workflow:**
```
Contract change
  ↓
Consumer discovery (contractguard.yaml / .yml across independent repos)
  ↓
Deterministic compatibility analysis (breaking vs compatible rules)
  ↓
Blast-radius analysis (confirmed vs likely source/test files, endpoints, fields)
  ↓
MCP integration (stdio JSON-RPC protocol for IBM Bob)
  ↓
IBM Bob agent repair (contract updates, DTO & test adaptations)
  ↓
Automated test suite execution (local compilation & unit tests)
  ↓
Deterministic verification (release safety gate: READY or BLOCKED)
  ↓
Evidence generation (tamper-evident audit artifacts with stable SHA-256 ID)
```

---

## 2. Starting Architecture

The starting prototype contained the fundamental end-to-end pipeline:
1. **OpenAPI loader & extractor (`loader.py`, `extractor.py`):** Basic YAML parsing and schema flattening.
2. **Deterministic rules (`rules.py`):** 5 rules (`check_removed_fields`, `check_type_changes`, `check_required_added`, `check_optional_added`, `detect_renames`).
3. **Comparator (`comparator.py`):** Compares a single producer and consumer contract pair.
4. **Consumer discovery (`discovery.py`):** Recursively finds `contractguard.yaml` files and evaluates declared dependencies.
5. **Impact analysis (`impact.py`):** Workspace text search for affected field names.
6. **AI Provider (`ai/`):** Direct Mistral API caller.
7. **MCP Server (`mcp_server.py`):** Hand-rolled JSON-RPC 2.0 stdio server.
8. **Evidence generator (`evidence.py`):** Generates JSON and Markdown audit reports.
9. **CLI (`__main__.py`):** Entrypoint for CLI subcommands.

---

## 3. Problems Discovered During Phase 1 Review

During our comprehensive inspection across areas A through I, the following weaknesses were uncovered:

1. **Non-Deterministic Finding Ordering in Rules & Comparator:**
   - In `rules.py`, `consumer_missing` and `producer_new` were un-ordered sets. Set iteration order in Python depends on hash randomization seeds, leading to non-deterministic rename matching if multiple fields changed simultaneously.
   - In `comparator.py`, findings were appended in discovery order rather than canonically sorted.
2. **Missing Endpoint Removal Rule:**
   - If a producer completely removed a path or method that a consumer required (e.g. `/api/v1/orders/{id}`), the comparison didn't evaluate schemas and silently reported `compatible` or caused key errors.
3. **Fragile Path & Directory Traversal:**
   - `impact.py` and `discovery.py` used unpruned recursive walks (`rglob("*")`), traversing deeply into `node_modules`, `.git`, `.venv`, and `target` directories, wasting CPU cycles and risking file access locks on Windows.
   - Discovery only looked for `contractguard.yaml` and ignored `contractguard.yml`.
4. **Silent Error Swallowing in Discovery:**
   - When a consumer's contract was missing, unreadable, or malformed, `ConsumerResult.error` was set, but `breaking_findings` was left empty. An agent inspecting `report.breaking_findings` saw zero findings despite the failure.
5. **Circular References & Incomplete Media Type Parsing:**
   - In `extractor.py`, recursive schemas with circular `$ref` (e.g., self-referencing tree nodes) caused Python `RecursionError`.
   - Content negotiation only matched exact `application/json`, ignoring vendor media types (e.g. `application/vnd.api+json`, `application/json;charset=utf-8`).
   - Top-level array response schemas (`type: array`, `items: ...`) were ignored by `flatten_properties`.
6. **Unstable Evidence Hashes:**
   - In `evidence.py`, `compute_stable_hash()` dumped `self.findings` without sorting. If findings appeared in varying order across runs or OS file system traversals, different SHA-256 hashes were generated for identical semantic states.
7. **Missing Blast-Radius Tools in MCP & CLI:**
   - Agents had no dedicated MCP tool to query deterministic blast radius without triggering an external LLM call.
   - The CLI lacked a dedicated `impact` subcommand.
8. **Over-Promising Claims Regarding Cryptographic Proof:**
   - Documentation and docstrings previously claimed that SHA-256 "certifies" release safety. In engineering terms, SHA-256 is a stable, tamper-evident content identifier, not a digital signature or authority certification.

---

## 4. Changes Implemented

### A. Deterministic Compatibility Engine (`models.py`, `rules.py`, `comparator.py`, `extractor.py`)
- **Added `ChangeKind.ENDPOINT_REMOVED` and `ChangeKind.CONTRACT_ERROR`:**
  Both mapped to `Severity.BREAKING` with explicit technical rationales.
- **Strictly Deterministic Field Pairing:**
  In `_detect_renames()`, `sorted(consumer_missing)` and `sorted(producer_new)` guarantee identical pair matching across platforms.
- **Removed Endpoint Detection:**
  `Comparator._compare_docs` checks if every consumer endpoint exists in the producer specification before checking schema fields.
- **Canonical Sorting of Findings:**
  All findings returned by `Comparator.compare()` are canonically sorted by `(endpoint, affected_field, change_kind)`.
- **Circular Reference & Top-Level Array Protection:**
  `flatten_properties` detects `$ref` cycles at property and item levels and returns safely. Top-level array schemas (`type: array`) are recursively flattened with `[]` prefix.

### B. Consumer Discovery (`discovery.py`, `config.py`)
- **Fast Pruned Directory Walk:**
  Replaced unpruned `rglob` with an `os.walk` that prunes `.git`, `node_modules`, `target`, `build`, `.gradle`, `venv`, etc.
- **Dual Extension Support:**
  Supports both `contractguard.yaml` and `contractguard.yml`.
- **Surfacing Errors as Actionable Findings:**
  When `load_config` or contract loading fails on a consumer, an explicit `ChangeKind.CONTRACT_ERROR` finding is recorded in `ConsumerResult.findings` and `DiscoveryReport.breaking_findings`.
- **Aggregate Blast Radius Property:**
  `DiscoveryReport.blast_radius_summary` exposes the aggregate `BlastRadiusSummary`.

### C. Blast-Radius Analysis (`impact.py`)
- **Explicit Aggregation Model (`BlastRadiusSummary`):**
  Aggregates affected services, contracts, endpoints, fields, confirmed source files, confirmed test files, likely source files, and likely test files.
- **Fast Pruned Code Scanning:**
  `scan_consumer_impact` prunes vendor/build directories during the token scan.
- **Preserved `consumer_root` Resolution:**
  Each `ConsumerImpact` records `consumer_root` so agents have absolute repo references.

### D. MCP Integration (`mcp_server.py`)
- **Added `get_blast_radius` Tool:**
  Enables Bob or any MCP client to retrieve pure deterministic blast-radius without invoking an LLM.
- **Rich Payload Schemas:**
  `discover_and_check_consumers` and `analyze_contract_impact` now include `blast_radius_summary`.
- **Robust Error Handling:**
  JSON-RPC calls return `isError: true` with actionable error descriptions rather than throwing unhandled exceptions.

### E. AI Layer (`ai/`)
- **Provider Abstraction (`LLMProvider`, `MistralProvider`, `ImpactAnalyzer`):**
  Clean interface separating deterministic findings from AI advisory reasoning.
- **Strict Advisory Guardrails:**
  AI output is structured via Pydantic schemas (`AIImpactReport`) and strictly advisory. It never decides or overrides compatibility verdicts.
- **Graceful Offline Fallback & Rate Limit Backoff:**
  Handles missing API keys, timeouts, network issues, and HTTP 429 rate limits gracefully. `CONTRACTGUARD_MOCK_AI=1` flag provides offline testing support. Secrets are never exposed.

### F. Verification & Evidence (`evidence.py`)
- **Deterministic Release Gate:**
  `evaluate_release_gate` requires 0 affected consumers and 0 breaking findings, plus passing test results, to grant `ReleaseStatus.READY`.
- **Canonical Hash Stability:**
  `compute_stable_hash()` canonically sorts findings prior to serialization, ensuring hash stability across platforms and traversal orders.
- **Refined Security Language:**
  Evidence is documented as a "tamper-evident identifier" (`cg-ev-<hash>`).

### G. CLI (`__main__.py`)
- **Added `impact` Command:**
  `contract-guard impact [workspace] [--format text|json] [--producer PRODUCER]`.
- **Consistent ANSI Banners & Exit Codes:**
  - `0`: Success / Compatible / Ready
  - `1`: Incompatible / Breaking / Blocked
  - `2`: User Error / Configuration Error

---

## 5. Summary of Deterministic Compatibility Rules

ContractGuard evaluates compatibility using 7 deterministic rules:

| Rule Name | Severity | Change Kind | Trigger Condition |
|---|:---:|:---:|---|
| Endpoint Removed | BREAKING | `endpoint_removed` | Consumer requires an endpoint (path + method) not present in producer. |
| Contract Error | BREAKING | `contract_error` | Missing, unreadable, or invalid YAML/OpenAPI contract or config. |
| Field Removed | BREAKING | `field_removed` | Field required by consumer is missing from producer response and cannot be paired as a rename. |
| Field Renamed | BREAKING | `field_renamed` | Field missing in producer, but a new field of the same type was added at the same endpoint level. |
| Type Changed | BREAKING | `field_type_changed` | Producer changed field type (e.g. `number` → `string`, `integer` → `object`). |
| Required Field Added | BREAKING | `field_required_added` | Producer marks a field as `required` when consumer treats it as optional or omitted. |
| Optional Field Added | COMPATIBLE | `field_optional_added` | Producer adds a field not in consumer contract and not marked required. |

---

## 6. Tests Added & Strengthened

The test suite was expanded from 83 to **92 tests**, all passing with **0 failures and 0 warnings**:

1. **`tests/test_comparator.py`:**
   - `TestEndpointRemoved.test_removed_endpoint_is_breaking`: Validates `ChangeKind.ENDPOINT_REMOVED` when an endpoint path is omitted.
   - `TestCircularReference.test_circular_ref_does_not_infinite_loop`: Validates that self-referencing schemas do not cause infinite recursion.
   - `TestArrayProperties.test_array_item_property_type_change_detected`: Validates top-level array property traversal and type change detection.
2. **`tests/test_discovery.py`:**
   - `test_discover_contractguard_yml`: Validates discovery of both `.yaml` and `.yml` configs.
   - `test_missing_contract_file_recorded_as_error`: Validates that contract load failures are recorded as `ChangeKind.CONTRACT_ERROR` in `breaking_findings`.
3. **`tests/test_evidence.py`:**
   - `test_evidence_hash_canonical_sorting_stability`: Validates that reversing or reordering findings yields the exact same evidence hash.
4. **`tests/test_mcp_server.py`:**
   - `test_mcp_call_get_blast_radius`: Validates calling `get_blast_radius` through JSON-RPC dispatch.
   - `test_mcp_tool_errors`: Validates recovery and `isError: true` responses for missing arguments or non-existent directories.
   - `test_mcp_lifecycle`: Validates `initialize` and `ping` methods.
5. **`tests/test_cli.py`:**
   - `test_cli_impact_text_and_json`: Validates `impact` subcommand with both human-readable text and agent-friendly JSON formats.
   - `test_cli_compare_and_check`: Validates `compare` and `check` subcommands.

---

## 7. Verification Results (Real Workspace Validation)

### A. Test Suite
- **Total Tests:** 92 passed in 1.79s.
- **Coverage:** Core modules `discovery.py` (100%), `models.py` (100%), `rules.py` (100%), `evidence.py` (99%), `comparator.py` (98%).

### B. CLI Commands on Parent Workspace (`..`)
```bash
python -m contract_guard discover ..
# Output: [OK] ALL CONSUMERS COMPATIBLE (3/3)
# Consumers: order-service, payment-client, reporting-service

python -m contract_guard impact ..
# Output: [OK] NO BLAST RADIUS - ALL CONSUMERS COMPATIBLE

python -m contract_guard verify ..
# Output: [OK] READY FOR RELEASE (Contract Status: PASS, Breaking Changes: 0)

python -m contract_guard evidence .. --output-dir ./scratch
# Output: [OK] EVIDENCE GENERATED - RELEASE APPROVED (Evidence ID: cg-ev-...)
```

### C. MCP Workflow Validation
- Dispatched `tools/list` → Returned 6 tools including `get_blast_radius`.
- Dispatched `get_blast_radius` on `..` → Returned 3 compatible consumers and empty affected services list.

### D. Breaking Change Simulation (`paymentAmount` → `totalAmount`)
- Legacy consumer (`paymentAmount`) vs Current Producer (`totalAmount`):
  `Compatible: False`
  `Findings: 1 (field_renamed paymentAmount -> totalAmount)`
- Repaired consumer state (`totalAmount` in all consumers):
  `3 consumers checked, 3 compatible, 0 breaking`.

---

## 8. Remaining Limitations (Phase 1)

1. **Protocol Scope:** Only OpenAPI 3.0.x / 3.1.x HTTP REST contracts in YAML format are supported (no JSON Schema standalone files, Protobuf, gRPC, GraphQL, or AsyncAPI).
2. **Local Workspace Only:** Repositories must reside in local directories accessible via relative paths from `contractguard.yaml`.
3. **No Automatic Pull Request Commenting:** Output is written to local files (`contractguard-evidence.json`, `contractguard-report.md`) or stdout.
4. **Advisory AST Scope:** Deep polymorphic schemas (`oneOf`, `anyOf`) are compared at the top property level; complex union discriminating rules are simplified.

---

## 9. Recommendations for Phase 2

1. **Git / CI/CD Integration:**
   - GitHub Actions / GitLab CI action runner.
   - PR comment bot that posts the Markdown evidence summary directly into pull requests.
2. **Semantic API Versioning Integration:**
   - Automatic SemVer bump advice (Major for breaking changes, Minor for backward-compatible additions, Patch for doc changes).
3. **AsyncAPI Protocol Extension:**
   - Extend the deterministic comparator to Kafka/RabbitMQ event payload schemas.
4. **Enhanced DTO Code Generators:**
   - Pre-generating patched client DTOs directly for Bob rather than requiring Bob to infer the Java/TypeScript syntax from raw YAML.
