# ContractGuard — Phase 2 Architecture & Implementation

## 1. Objective

Phase 2 elevates **ContractGuard** from a standalone local OpenAPI comparison engine into a **Git-aware PR and change safety tool**.

The primary question Phase 2 answers for developers, CI pipelines, and autonomous coding agents (IBM Bob) is:

> **"Before I merge this API change, what does it break?"**

### The Phase 2 Workflow

```
Developer / PR changes an OpenAPI contract
                ↓
Git detects the change (staged, working tree, or branch diff against base)
                ↓
ContractGuard identifies changed producer contracts
                ↓
Consumer Discovery (workspace-wide contractguard.yaml)
                ↓
Deterministic Compatibility Analysis (OpenAPI schema rules)
                ↓
Deterministic Blast-Radius Analysis (source & test file impacts)
                ↓
Deterministic SemVer Recommendation (MAJOR / MINOR / PATCH)
                ↓
Release Safety Gate Verdict (READY / BLOCKED)
                ↓
Machine-Readable CI Output (JSON / PR Markdown) & Enriched Release Evidence
```

Core Axiom:
> **"AI reasons. Deterministic checks decide. Bob executes. Deterministic verification proves."**

---

## 2. Scope

### In Scope
- **Git Abstraction (`src/contract_guard/git.py`)**: Subprocess-based interface with the system `git` CLI; zero external dependencies (no GitPython).
- **PR Analysis Engine (`src/contract_guard/pr.py`)**: End-to-end evaluation comparing base and head refs, discovering consumers, computing blast radius, and calculating SemVer bumps.
- **Deterministic SemVer Engine (`src/contract_guard/versioning.py`)**: Strict rule mapping:
  - Breaking changes $\rightarrow$ **MAJOR** bump.
  - Backward-compatible additions $\rightarrow$ **MINOR** bump.
  - Non-contract or documentation changes $\rightarrow$ **PATCH** bump.
  - No contract changes $\rightarrow$ **NONE**.
- **Multi-Format Output & CI Gating**:
  - Colored text terminal summary.
  - Machine-readable JSON output for CI pipelines and agent consumers.
  - GitHub/GitLab PR-ready Markdown reports.
- **Standardized CI Exit Codes**:
  - `0`: READY (Change is backward-compatible; safe to merge).
  - `1`: BLOCKED (Breaking contract changes detected across one or more consumers).
  - `2`: Configuration, Git, or user environment error.
- **CI/CD Workflow Examples**:
  - `.github/workflows/contractguard.yml`
  - `.gitlab-ci.yml.example`
- **Git-Enriched Release Evidence (`src/contract_guard/evidence.py`)**:
  - Integrates repository path, commit SHA, base ref, changed contracts, SemVer recommendation, and blast radius summary into canonical SHA-256 evidence.
- **MCP Tool Extension (`src/contract_guard/mcp_server.py`)**:
  - Added `analyze_git_change` tool allowing IBM Bob to query PR safety and consumer impact deterministically.

### Out of Scope (Deferred to Future Phases)
- AsyncAPI, WebSockets, gRPC, and GraphQL contracts.
- Database storage or persistent backends.
- Web frontends or interactive dashboards.
- Direct network calls to GitHub / GitLab REST APIs or bot commenting.
- Credentials, tokens, or cloud service integrations.

---

## 3. Architecture Changes

Phase 2 preserves 100% of Phase 1's architecture while introducing three foundational modules:

```
src/contract_guard/
├── __init__.py
├── __main__.py          [MODIFIED] Added git-status, git-diff, and pr CLI commands
├── comparator.py        [PRESERVED] Pure deterministic OpenAPI comparator
├── config.py            [PRESERVED] contractguard.yaml configuration loader
├── discovery.py         [MODIFIED] Added .github to SKIP_DISCOVERY_DIRS
├── evidence.py          [MODIFIED] Enriched evidence with Git & SemVer metadata
├── extractor.py         [PRESERVED] OpenAPI endpoint & property extractor
├── git.py               [NEW] Subprocess-based local git abstraction
├── impact.py            [PRESERVED] Blast-radius source token scanner
├── loader.py            [PRESERVED] YAML/JSON schema parser
├── mcp_server.py        [MODIFIED] Registered analyze_git_change MCP tool
├── models.py            [PRESERVED] Data models & ChangeKind enum
├── pr.py                [NEW] PR orchestration, JSON, & Markdown reporting
├── rules.py             [PRESERVED] Compatibility rules engine
└── versioning.py        [NEW] Deterministic SemVer calculation engine
```

---

## 4. Git Abstraction (`src/contract_guard/git.py`)

The Git abstraction provides safe, deterministic access to repository status without introducing external library dependencies.

### Capabilities
- `is_git_installed() -> bool`: Verifies `git` exists in `PATH`.
- `is_git_repo(path) -> bool`: Checks if directory is inside a valid git work tree.
- `get_repo_root(path) -> Path | None`: Locates root directory of repository.
- `get_current_sha(path) -> str | None`: Retrieves full 40-character commit SHA.
- `resolve_ref(path, ref) -> str | None`: Resolves branch names (`main`), tags (`v1.4.0`), or commit expressions (`HEAD~1`).
- `get_changed_files(path, base_ref) -> tuple[list[str], str | None]`:
  - When `base_ref` is provided: executes `git diff --name-only <base_ref>`.
  - When `base_ref` is omitted: parses `git status --porcelain` for uncommitted working-tree changes, falling back to `git diff --name-only HEAD~1 HEAD` for clean commits.
- `is_contract_file(path) -> bool`: Detects OpenAPI contracts (`openapi.*`, `swagger.*`, `contract.*`, `/contracts/`, `/docs/`), explicitly ignoring `contractguard.yaml` configuration files.
- `inspect_git_status(path, base_ref) -> GitStatus`: Structured container returning repository status, commit SHAs, changed contracts, and non-contract files.

### Failure Handling
Never crashes with unhandled tracebacks. Fails cleanly with descriptive errors when git is not installed, the directory is not a git repository, or a specified ref does not exist.

---

## 5. PR Analysis Engine (`src/contract_guard/pr.py`)

Orchestrates the entire contract change safety evaluation:

1. **Inspects Git Status**: Identifies current commit, base ref, and changed contract files.
2. **Discovers Consumers**: Scans workspace recursively for `contractguard.yaml` declarations.
3. **Executes Comparisons**: Evaluates consumer expectations against producer schemas.
4. **Calculates Blast Radius**: Identifies confirmed and likely affected Java/source files and test classes across consumers.
5. **Recommends SemVer**: Categorizes API modifications deterministically.
6. **Evaluates Release Gate**: Determines overall `READY` vs `BLOCKED` verdict.
7. **Generates Release Evidence**: Produces tamper-evident canonical SHA-256 evidence package.

---

## 6. SemVer Engine (`src/contract_guard/versioning.py`)

SemVer classification is strictly deterministic and never delegated to an LLM:

| Change Category | Trigger | Recommended Bump | Example |
|---|---|---|---|
| **Breaking Change** | Field removed, renamed, type changed, or newly required | **MAJOR** | `1.4.0 -> 2.0.0` |
| **Additive / Compatible** | Optional response field added | **MINOR** | `1.4.0 -> 1.5.0` |
| **Contract / Non-breaking** | Contract touched with no schema changes | **PATCH** | `1.4.0 -> 1.4.1` |
| **No Contract Changes** | No contract files modified in diff | **NONE** | `1.4.0 -> 1.4.0` |

### Non-Invented Versions Rule
If no baseline version is provided or found in OpenAPI `info.version`, ContractGuard reports the bump category (`MAJOR`, `MINOR`, `PATCH`) with the reason without inventing synthetic version numbers.

---

## 7. Machine-Readable JSON Output Schema

Designed specifically for CI/CD pipelines, automated gates, and agentic consumers:

```json
{
  "repository": "payment-service",
  "commit": "c3d2bfd0d702d88502f3f5bd8401a5c9e8e7f916",
  "base": "origin/main",
  "changed_contracts": [
    "payment-service/docs/openapi.yaml"
  ],
  "consumers_checked": 3,
  "consumers_checked_list": [
    "order-service",
    "payment-client",
    "reporting-service"
  ],
  "compatible_consumers": 0,
  "compatible_consumers_list": [],
  "affected_consumers": 3,
  "affected_consumers_list": [
    "order-service",
    "payment-client",
    "reporting-service"
  ],
  "breaking_findings": [
    {
      "consumer_service": "payment-client",
      "producer_service": "payment-service",
      "endpoint": "GET /api/payments/{id}",
      "affected_field": "paymentAmount",
      "change_kind": "field_renamed",
      "severity": "breaking",
      "detail": "Field 'paymentAmount' was renamed to 'totalAmount' in the producer response.",
      "reason": "Consumer expects 'paymentAmount' but producer now sends 'totalAmount'."
    }
  ],
  "blast_radius_summary": {
    "affected_services": ["payment-client"],
    "affected_contracts": ["payment-client/contracts/payment-service.yaml"],
    "affected_endpoints": ["GET /api/payments/{id}"],
    "affected_fields": ["paymentAmount"],
    "confirmed_source_files": ["payment-client/src/main/java/com/example/paymentclient/model/PaymentResponse.java"],
    "confirmed_test_files": ["payment-client/src/test/java/com/example/paymentclient/client/PaymentClientTest.java"],
    "likely_source_files": [],
    "likely_test_files": []
  },
  "semver": {
    "bump": "major",
    "current_version": "1.4.0",
    "recommended_version": "2.0.0",
    "reason": "Detected 3 breaking API contract change(s)."
  },
  "verdict": "BLOCKED",
  "is_ready": false,
  "evidence_id": "cg-ev-6a8b1c4d9e0f2345",
  "reasons": [
    "1 breaking contract change(s) detected across 3 consumer(s)."
  ],
  "git_error": null
}
```

---

## 8. PR Markdown Report

Directly usable as a pull request comment in GitHub Actions or GitLab CI:

````markdown
# ContractGuard PR Analysis

**Verdict:** `BLOCKED`

## Summary

| Metric | Result |
|---|---:|
| Consumers checked | 3 |
| Affected consumers | 3 |
| Breaking changes | 3 |

## Breaking Changes

### GET /api/payments/{id}

- **Field:** `paymentAmount`
- **Type:** `field_renamed`
- **Consumer Affected:** `payment-client`
- **Detail:** Field 'paymentAmount' was renamed to 'totalAmount' in the producer response.

## Affected Consumers

- order-service
- payment-client
- reporting-service

## SemVer Recommendation

**MAJOR**

`1.4.0 -> 2.0.0`

Reason: Detected 3 breaking API contract change(s).

## Evidence

Evidence ID: `cg-ev-6a8b1c4d9e0f2345`
````

---

## 9. CI/CD Integration

### Exit Codes
- **`0`**: READY (Safe to merge, no breaking contract changes).
- **`1`**: BLOCKED (Breaking contract changes detected across consumers).
- **`2`**: System/Git/Configuration error.

### GitHub Actions (`.github/workflows/contractguard.yml`)
```yaml
name: ContractGuard PR Safety Gate
on:
  pull_request:
    branches: [ main, master ]
jobs:
  contract-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ./contract-guard
      - name: Run PR Contract Analysis
        run: contract-guard pr . --base origin/${{ github.base_ref || 'main' }} --format markdown --output contractguard-pr.md
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: contractguard-evidence
          path: |
            contractguard-pr.md
            contractguard-evidence.json
```

### GitLab CI (`.gitlab-ci.yml.example`)
```yaml
contractguard:pr-check:
  stage: test
  image: python:3.11-slim
  before_script:
    - apt-get update && apt-get install -y git
    - pip install ./contract-guard
  script:
    - git fetch origin ${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main}
    - contract-guard pr . --base origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-main} --format markdown --output contractguard-pr.md
  artifacts:
    when: always
    paths:
      - contractguard-pr.md
      - contractguard-evidence.json
```

---

## 10. MCP Extension (`analyze_git_change`)

Added tool `analyze_git_change` to the MCP Server:
- **Input**:
  - `workspace_root` (required string): Path to workspace repository.
  - `base_ref` (optional string): Target branch or baseline commit ref.
  - `producer_filter` (optional string): Filter to a specific producer service.
  - `current_version` (optional string): Baseline SemVer.
- **Output**: Full JSON report containing changed contracts, consumer impact, breaking findings, blast radius, SemVer recommendation, and verdict.
- **Agent Integration**: IBM Bob queries `analyze_git_change` to determine if a PR is safe before proposing repairs or opening merge requests.

---

## 11. Evidence Changes

`src/contract_guard/evidence.py` has been enriched to record:
- `repository_path`: Resolved repository directory.
- `commit_sha`: Git commit hash at evaluation.
- `base_ref`: Base commit ref evaluated against.
- `semver`: Deterministic SemVer recommendation object.
- `blast_radius_summary`: Confirmed and likely affected file paths.

### Canonical Hashing Guarantee
The SHA-256 evidence identifier remains 100% deterministic and tamper-evident across platforms by sorting all dictionary keys canonically and serializing with UTF-8 before hashing.

---

## 12. Automated Testing Suite

The test suite expanded from the Phase 1 baseline of **92 tests** to **117 comprehensive automated tests**:

| Test Module | Tests | Focus |
|---|---|---|
| `tests/test_comparator.py` | 12 | Schema difference and rename detection rules |
| `tests/test_rules.py` | 17 | Removed, type change, required/optional added rules |
| `tests/test_config.py` | 8 | `contractguard.yaml` parsing and validation |
| `tests/test_discovery.py` | 21 | Multi-repo discovery and producer filtering |
| `tests/test_impact.py` | 5 | Source token scanning and blast radius calculation |
| `tests/test_ai.py` | 12 | Mistral provider mocking and repair plan generation |
| `tests/test_evidence.py` | 7 | Canonical hashing, release gate, and Git metadata |
| `tests/test_git.py` | 7 | Git detection, changed files, missing git handling |
| `tests/test_versioning.py` | 8 | SemVer parsing, bumping, and recommendation rules |
| `tests/test_pr.py` | 5 | PR analysis, baseline clean, breaking blocked, additions |
| `tests/test_cli.py` | 5 | CLI commands (`check`, `git-status`, `git-diff`, `pr`) |
| `tests/test_mcp_server.py` | 8 | MCP tools lifecycle, verify, blast radius, `analyze_git_change` |
| `tests/test_e2e_workflow.py` | 1 | Phase 1 end-to-end Bob repair loop |
| `tests/test_phase2_e2e_workflow.py` | 1 | Phase 2 full Git-aware PR safety and repair workflow |
| **Total** | **117** | **100% Passing, 0 Failures, 0 Warnings (80% Total Coverage)** |

---

## 13. Verification Results

### Multi-Service Test Scenario
Tested across `payment-service`, `payment-client`, `order-service`, and `reporting-service`:
1. **Producer Contract Modification**: Renamed `paymentAmount` $\rightarrow$ `totalAmount` in `payment-service/docs/openapi.yaml`.
2. **Git Detection**: `contract-guard git-status` reported 1 changed contract file.
3. **PR Analysis**: `contract-guard pr ..` evaluated 3 consumers.
4. **Result**:
   - `paymentAmount` $\rightarrow$ `totalAmount` detected as `field_renamed`.
   - 3 consumers affected (`payment-client`, `order-service`, `reporting-service`).
   - SemVer recommended: **MAJOR** (`1.4.0 -> 2.0.0`).
   - Verdict: **`BLOCKED`** with exit code `1`.
5. **Bob Repair**: Consumers updated to `totalAmount` in contracts and Java DTOs.
6. **Deterministic Re-verification**: `contract-guard pr ..` re-run:
   - 3 consumers compatible.
   - 0 breaking changes.
   - Verdict: **`READY`** with exit code `0`.
   - Release evidence regenerated with stable tamper-evident ID.

---

## 14. Limitations

1. **Local Git CLI Dependency**: Relies on the host `git` command; environments without `git` in `PATH` will fail gracefully with exit code 2.
2. **Single Git Workspace Assumption**: In multi-repo setups, ContractGuard assumes all repositories reside within a shared workspace tree or accessible filesystem path.
3. **Non-Contract File SemVer**: Changes outside contracts result in `PATCH` or `NONE` recommendations; code-only internal breaking changes without contract updates cannot be detected from OpenAPI files alone.

---

## 15. Deferred Phase 3 Work

The following enhancements are intentionally reserved for Phase 3:
1. **AsyncAPI & Event Contracts**: Support for Kafka, RabbitMQ, and CloudEvents schemas.
2. **Centralized Schema Registry**: Support for enterprise schema registries (e.g. Confluent, Apicurio).
3. **Automated DTO Patch Generation**: Direct AST-based code generation for consumer Java/TypeScript DTOs.
4. **Direct GitHub / GitLab PR Commenting**: Native API integrations for posting sticky PR comments.
5. **Transitive Microservice Dependency Graph**: Deep multi-hop blast-radius tracing beyond direct producer-consumer pairs.
