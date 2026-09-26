# ContractGuard

> **"Your API changed. Did every consumer change with it?"**  
> **"AI reasons. Deterministic checks decide. Bob executes. Evidence proves."**

ContractGuard is a deterministic API contract compatibility engine, blast-radius analyzer, and release verification gate for modern microservice architectures. Built for the **IBM Bob 2.0 Hackathon**, ContractGuard empowers autonomous coding agents (like IBM Bob) to detect breaking API changes across multiple independent consumer repositories, explain the impact with Mistral AI, execute verified repairs, and produce reproducible release evidence.

---

## Architecture & Principles

ContractGuard strictly enforces separation of concerns between deterministic logic, AI reasoning, and agent execution:

```
                            ┌──────────────────────────────────────────────┐
                            │               API Contract Change            │
                            └──────────────────────┬───────────────────────┘
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ DETERMINISTIC ENGINE (ContractGuard Core)                                                       │
│  - Multi-repo Consumer Discovery (contractguard.yaml)                                           │
│  - OpenAPI 3.x AST Comparison & Rule Evaluation                                                 │
│  - Verdict Decision (BREAKING vs COMPATIBLE)                                                    │
│  - Blast-Radius File Inspection (Confirmed vs Likely Source & Test Files)                       │
└──────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                   │ Findings & Minimal Context
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ AI REASONING LAYER (Mistral AI via LLMProvider Abstraction)                                     │
│  - Explains what changed & why it breaks downstream consumers                                   │
│  - Distinguishes CONFIRMED facts from INFERRED impacts                                          │
│  - Generates Step-by-Step Advisory Repair Plan & Backward-Compatible Migration Options         │
│  - Never overrides deterministic verdicts                                                       │
└──────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                   │ Structured MCP Response (JSON-RPC)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ AUTONOMOUS EXECUTION (IBM Bob via MCP)                                                          │
│  - Reads structured findings & repair plan                                                      │
│  - Edits consumer contracts, DTOs, services, and test fixtures                                  │
│  - Runs test suites locally                                                                     │
└──────────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                   │ Re-verify Trigger
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ DETERMINISTIC RELEASE GATE & EVIDENCE                                                           │
│  - Final Compatibility Check (0 affected consumers required)                                    │
│  - Release Safety Gate: READY or BLOCKED                                                         │
│  - Audit Artifacts: contractguard-evidence.json & contractguard-report.md (Stable SHA-256 Hash) │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Deterministic vs. AI Responsibilities

| Responsibility | Deterministic Engine | Mistral AI | IBM Bob |
|---|:---:|:---:|:---:|
| Contract parsing & diffing | **Authoritative** | ❌ Forbidden | ❌ |
| Breaking / Compatible verdict | **Decides** | ❌ Cannot override | ❌ |
| Consumer discovery & dependency graph | **Authoritative** | ❌ | ❌ |
| Blast-radius file identification | **Confirmed Facts** | Inferred / Likely | ❌ |
| Impact explanation & developer rationale | ❌ | **Explains** | ❌ |
| Advisory repair plan & migration advice | ❌ | **Proposes** | ❌ |
| Code editing & file modifications | ❌ | ❌ Advisory only | **Executes** |
| Test suite execution | ❌ | ❌ | **Executes** |
| Release gate (READY / BLOCKED) | **Decides** | ❌ | ❌ |
| Reproducible release evidence generation | **Proves** | ❌ | ❌ |

---

## Why Tests Alone Are Insufficient

In this demo, consumer tests can remain green because HTTP interactions are mocked locally. ContractGuard independently checks the producer and consumer contracts to detect wire-level incompatibility.

In microservice client repositories (such as `payment-client`), HTTP interactions are typically mocked using frameworks like Spring's `MockRestServiceServer` or WireMock. When a producer changes a response field (e.g., `paymentAmount` → `totalAmount`):
1. Consumer unit and integration tests continue asserting against hardcoded JSON fixtures expecting `paymentAmount`.
2. The consumer test suite **passes 100% green**.
3. In production, real HTTP responses contain `totalAmount`. Depending on the consumer's DTO configuration and deserialization behavior, the changed response can lead to missing data, deserialization errors, or downstream failures.

**ContractGuard catches this incompatibility statically at the contract level without needing to boot or run live services.**

---

## Workspace Layout

ContractGuard works across independent repositories:

```
IBM BOB HACKATHON/
├── contract-guard/           # Python engine, CLI, MCP Server, Evidence Generator
├── payment-service/          # Producer service (Java/Spring Boot, docs/openapi.yaml)
├── payment-client/           # Consumer service (Java/Spring Boot, contracts/payment-service.yaml)
├── order-service/            # Lightweight consumer (contracts/payment-service.yaml)
└── reporting-service/        # Lightweight consumer (contracts/payment-service.yaml)
```

Each consumer repository declares its dependencies in `contractguard.yaml`:
```yaml
service: payment-client

dependencies:
  - service: payment-service
    consumer_contract: contracts/payment-service.yaml
    producer_contract: ../payment-service/docs/openapi.yaml
```

---

## Installation & Setup

### Requirements
- Python 3.9+
- JDK 21 & Maven 3.9+ (for running Java consumer/producer services)

### Setup ContractGuard
```bash
cd contract-guard

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate   # macOS / Linux

# Install dependencies and package in editable mode
pip install -e ".[dev]"
```

### Environment Variables
Configure Mistral AI for impact analysis (optional — ContractGuard works 100% deterministically without an API key):

```bash
# Windows (PowerShell)
$env:MISTRAL_API_KEY="your-mistral-api-key"
$env:MISTRAL_MODEL="mistral-small-latest"     # Optional: defaults to mistral-small-latest
$env:MISTRAL_API_BASE="https://api.mistral.ai/v1" # Optional
$env:MISTRAL_TIMEOUT="30.0"                  # Optional

# Linux / macOS
export MISTRAL_API_KEY="your-mistral-api-key"
export MISTRAL_MODEL="mistral-small-latest"
```

> **Security Note:** If `MISTRAL_API_KEY` is not set, ContractGuard functions normally in deterministic mode. AI features return a clean `"AI analysis unavailable"` status. Secrets are never logged or exported in evidence reports.

---

## CLI Usage

ContractGuard provides readable CLI commands for developers and live hackathon demos:

### 1. Consumer Discovery & Blast Radius
Scan the entire workspace for all declared consumers, compare contracts, and inspect affected files:
```bash
contract-guard discover ..
```

Output:
```
[!!] 3/3 CONSUMERS AFFECTED BY CONTRACT DRIFT

  Workspace Root    : D:\Code\IBM BOB Hackathon
  Configs Discovered: 3
  Consumers Checked : order-service, payment-client, reporting-service
  Compatible        : None
  Affected          : order-service, payment-client, reporting-service

Deterministic Blast Radius & Impact Analysis:

  Consumer  : payment-client
  Contract  : contracts/payment-service.yaml
  Endpoint  : GET /api/payments/{id}
  Field     : paymentAmount (field_renamed)
  Detail    : Consumer expects 'paymentAmount' but producer now uses 'totalAmount'
    Confirmed Affected Source Files:
      - src/main/java/com/example/paymentclient/model/PaymentResponse.java
      - src/main/java/com/example/paymentclient/service/PaymentDisplayService.java
    Confirmed Affected Test Files:
      - src/test/java/com/example/paymentclient/client/PaymentClientTest.java
      - src/test/java/com/example/paymentclient/model/PaymentResponseSerializationTest.java
      - src/test/java/com/example/paymentclient/service/PaymentDisplayServiceTest.java
    Likely Affected Source Files:
      - src/main/java/com/example/paymentclient/client/PaymentClient.java
```

### 2. AI Impact Explanation & Repair Plan
Execute deterministic discovery and invoke Mistral AI for a structured explanation and advisory repair plan:
```bash
contract-guard analyze ..
```

### 3. Release Safety Gate
Evaluate whether changes are safe to release (`READY` vs `BLOCKED`):
```bash
contract-guard verify .. --producer payment-service --test-status PASS
```

### 4. Release Evidence Generation
Generate machine-readable audit artifacts (`contractguard-evidence.json` and `contractguard-report.md`):
```bash
contract-guard evidence .. --producer payment-service --output-dir ./release-evidence
```

### 5. Pairwise Comparison & Config Check
```bash
contract-guard compare ../payment-service/docs/openapi.yaml ../payment-client/contracts/payment-service.yaml
contract-guard check ../payment-client/contractguard.yaml
```

---

## IBM Bob MCP Integration

ContractGuard runs an MCP (Model Context Protocol) stdio server over JSON-RPC 2.0. IBM Bob connects to this server to discover consumers, analyze impact, execute repairs, and verify release readiness.

### Available MCP Tools

ContractGuard exposes 7 deterministic and AI-assisted tools over the Model Context Protocol:

| Tool | Purpose | Key Inputs |
|---|---|---|
| `compare_contracts` | Pairwise comparison between two OpenAPI YAML files | `producer_path`, `consumer_path` |
| `read_contractguard_config` | Parse a single `contractguard.yaml` and resolve paths | `config_path` |
| `discover_and_check_consumers` | Recursive workspace discovery and blast-radius calculation | `workspace_root`, `producer_filter` |
| `get_blast_radius` | Scan consumer codebases for impacted source and test files | `workspace_root`, `producer_filter` |
| `analyze_contract_impact` | Discovery + blast radius + Mistral AI explanation and advisory repair plan | `workspace_root`, `producer_filter` |
| `verify_release_safety` | Release gate verification (`READY`/`BLOCKED`) and evidence artifact generation | `workspace_root`, `producer_service`, `test_status`, `output_dir` |
| `analyze_git_change` | Git-aware PR change analysis, blast radius, SemVer recommendation, and verdict | `workspace_root`, `base_ref`, `producer_filter`, `current_version` |

### Registering with IBM Bob

Add ContractGuard to `.bob/mcp.json` or your global Bob configuration:

```json
{
  "mcpServers": {
    "contract-guard": {
      "command": "C:/path/to/contract-guard/.venv/Scripts/python.exe",
      "args": ["-m", "contract_guard.mcp_server"],
      "env": {
        "MISTRAL_API_KEY": "your-mistral-api-key"
      }
    }
  }
}
```

---

## Hackathon Demo Scenario (2–3 Minute Flow)

### 1. Baseline State
All 3 consumers (`payment-client`, `order-service`, `reporting-service`) expect `paymentAmount`.
```bash
contract-guard discover ..
# Output: [OK] ALL CONSUMERS COMPATIBLE (3/3)
contract-guard verify ..
# Output: [OK] READY FOR RELEASE
```

### 2. Breaking API Change
In `payment-service/docs/openapi.yaml`, the producer renames `paymentAmount` to `totalAmount`:
```yaml
# Before:
required: [id, paymentAmount, currency, status]
properties:
  paymentAmount: { type: number, format: double }

# After:
required: [id, totalAmount, currency, status]
properties:
  totalAmount: { type: number, format: double }
```

### 3. Consumer Tests Pass Green (The Trap)
Run tests in `payment-client`:
```bash
cd ../payment-client && mvn test
```
**Tests pass green!** The mock HTTP tests do not catch the break.

### 4. ContractGuard Catches the Drift
```bash
contract-guard discover ..
# Output: [!!] 3/3 CONSUMERS AFFECTED
contract-guard verify ..
# Output: [BLOCKED] RELEASE BLOCKED
```

### 5. AI Impact Analysis via Bob
Bob calls `analyze_contract_impact` through MCP and receives:
- Exact confirmed broken files (`PaymentResponse.java`, `PaymentDisplayService.java`)
- Test files needing updates (`PaymentClientTest.java`, `PaymentResponseSerializationTest.java`, `PaymentDisplayServiceTest.java`)
- Advisory 7-step repair plan.

### 6. Bob Executes Repairs
Bob updates:
1. `contracts/payment-service.yaml` in `payment-client`, `order-service`, and `reporting-service` to `totalAmount`.
2. `PaymentResponse.java` (`@JsonProperty("totalAmount")`, `private BigDecimal totalAmount`).
3. Getter/setter in `PaymentResponse.java` and usages in `PaymentDisplayService.java`.
4. Test fixtures in `PaymentClientTest.java`, `PaymentResponseSerializationTest.java`, `PaymentDisplayServiceTest.java`.

### 7. Re-verify & Release Evidence
```bash
# Deterministic re-check:
contract-guard discover ..
# Output: [OK] ALL CONSUMERS COMPATIBLE (3/3)

# Deterministic release gate:
contract-guard verify ..
# Output: [OK] READY FOR RELEASE

# Generate reproducible evidence:
contract-guard evidence .. --output-dir ./release-evidence
```

The generated evidence contains a stable SHA-256 identifier that makes the evidence artifact tamper-evident.

---

## Phase 2 — Git & PR Safety

Phase 2 elevates ContractGuard from a local analysis engine into a **Git-aware PR and change safety tool**. It answers the critical pre-merge question:

> **"Before I merge this API change, what does it break?"**

### Phase 2 Architecture Flow

```
Git Change (Diff / Branch / PR)
                ↓
    ContractGuard PR Engine
                ↓
Consumer Impact & Blast Radius
                ↓
Deterministic SemVer Bump (MAJOR / MINOR / PATCH)
                ↓
Safety Verdict (READY vs BLOCKED)
                ↓
CI / PR Output (Markdown / JSON / Exit Code)
```

### Why ContractGuard is Git-Aware
In real engineering teams, contract modifications happen inside branches, pull requests, and commit diffs. By coupling the deterministic OpenAPI engine with Git:
- Only modified contract files are evaluated for drift.
- Baseline contracts can be extracted directly from git refs (e.g. `origin/main`, `HEAD~1`).
- The SemVer recommendation is strictly anchored in the actual semantic change between target branch and PR branch.
- CI pipelines can automatically gate pull requests before merge.

### Phase 2 CLI Commands

| Command | Purpose |
|---|---|
| `contract-guard git-status [dir]` | Detect repository status, current commit SHA, and changed OpenAPI contracts. |
| `contract-guard git-diff [dir] [--base ref]` | Inspect files and OpenAPI contracts modified relative to a base ref or working tree. |
| `contract-guard pr [dir] [--base ref]` | Primary Phase 2 PR command: evaluates contract diffs against consumers, recommends SemVer, and returns READY/BLOCKED verdict. |

#### Output Formats & Flags
- `--format text` (default): Human-readable terminal output with colored banners.
- `--format json`: Machine-readable JSON structured for CI gates, scripting, and agent consumers.
- `--format markdown`: GitHub/GitLab PR-ready summary table and breakdown.
- `--output file.md`: Write formatted report directly to a file for CI comments.
- `--base ref`: Explicit Git ref to compare against (e.g. `origin/main`, `HEAD~1`).

### Deterministic SemVer Rules
SemVer recommendations are strictly derived from the producer API contract change relative to its Git base:
- **Breaking producer contract change** $\rightarrow$ **`MAJOR`**
- **Compatible additive producer contract change** $\rightarrow$ **`MINOR`**
- **Contract touched but no schema/API compatibility change** $\rightarrow$ **`PATCH`**
- **No contract changes** $\rightarrow$ **`NONE`**

The recommendation reflects the intrinsic nature of the producer change, independent of whether downstream consumers have already been repaired.

### Exit Code Philosophy
ContractGuard follows strict, deterministic CI exit codes:
- **`0` = `READY`**: All discovered consumer contracts are compatible with the proposed producer change.
- **`1` = `BLOCKED`**: One or more discovered consumers are incompatible with the proposed producer change.
- **`2` = `ERROR`**: Git, configuration, environment, or analysis error.

---

## Phase 2 Demo Workflow

The complete Phase 2 Git-aware PR safety workflow can be demonstrated in 8 reproducible steps:

### 1. Clean Baseline Repository
```bash
contract-guard git-status ..
# Git Repository: YES, Changed Contracts: 0
contract-guard pr ..
# Output: [OK] PR SAFE TO MERGE - READY (Exit 0, SemVer NONE)
```

### 2. Introduce Breaking Contract Change
In `payment-service/docs/openapi.yaml`, rename `paymentAmount` to `totalAmount`:
```yaml
required: [id, totalAmount, currency, status]
properties:
  totalAmount: { type: number, format: double }
```

### 3. Git Detects the Contract Change
```bash
contract-guard git-diff ..
# Changed Contracts (1):
#   - payment-service/docs/openapi.yaml
```

### 4. Run PR Analysis (BLOCKED)
```bash
contract-guard pr .. --base origin/main
```
Output:
```
[BLOCKED] PR CONTAINS BREAKING API CHANGES

CONTRACTGUARD -- PR ANALYSIS
  Repository        : IBM BOB Hackathon
  Commit            : abc1234
  Base Ref          : origin/main

Changed Contracts:
  - payment-service/docs/openapi.yaml

Consumers Checked: 3
  Compatible        : 0
  Affected          : 3
  Breaking Changes  : 3

Breaking changes:
  GET /api/payments/{id}
  paymentAmount -> totalAmount
  change: field_renamed

Affected consumers:
  - payment-client
  - order-service
  - reporting-service

Recommended SemVer:
  1.4.0 -> 2.0.0 (MAJOR)
  Reason: Detected 1 breaking API contract change(s).

Verdict:
  BLOCKED

Evidence ID:
  cg-ev-6a8b1c4d9e0f2345
```
*(Command terminates with exit code 1, automatically blocking CI pull request merge).*

### 5. Generate Machine-Readable CI JSON & PR Markdown
```bash
# Generate CI JSON
contract-guard pr .. --format json

# Generate PR Comment Markdown
contract-guard pr .. --format markdown --output contractguard-pr.md
```

### 6. Bob Repairs Affected Consumers
IBM Bob uses MCP tool `analyze_git_change` to identify broken fields, then repairs:
- `payment-client/contracts/payment-service.yaml`
- `order-service/contracts/payment-service.yaml`
- `reporting-service/contracts/payment-service.yaml`
- Java DTOs and test fixtures in `payment-client`.

### 7. Re-run PR Analysis (READY with MAJOR SemVer)
```bash
contract-guard pr .. --base origin/main
```
Output:
```
[OK] PR SAFE TO MERGE - READY

CONTRACTGUARD -- PR ANALYSIS
  Repository        : IBM BOB Hackathon
  Commit            : def5678

Changed Contracts:
  - order-service/contracts/payment-service.yaml
  - payment-client/contracts/payment-service.yaml
  - payment-service/docs/openapi.yaml
  - reporting-service/contracts/payment-service.yaml

Consumers Checked: 3
  Compatible        : 3
  Affected          : 0
  Breaking Changes  : 0

Recommended SemVer:
  1.4.0 -> 2.0.0 (MAJOR)
  Reason: Producer contract contains a breaking change, but all discovered consumers are compatible.

Verdict:
  READY
```
*(Command terminates with exit code 0, clearing CI pull request for merge).*

> **Important Semantic Distinction:**
> - **SemVer** reflects the nature of the producer API change (`paymentAmount` $\rightarrow$ `totalAmount` is a breaking schema change $\rightarrow$ `MAJOR`).
> - **Verdict** reflects the compatibility of discovered consumers (all 3 discovered consumers have been repaired $\rightarrow$ `READY`).
> - **Breaking + Incompatible Consumers** $\rightarrow$ `MAJOR` + `BLOCKED` (exit 1).
> - **Breaking + Repaired/Compatible Consumers** $\rightarrow$ `MAJOR` + `READY` (exit 0).

### 8. Release Evidence Generation
```bash
contract-guard evidence .. --producer payment-service --output-dir ./release-evidence
```
The evidence artifact is deterministically generated with Git commit SHA, base ref, SemVer recommendation, and tamper-evident SHA-256 content identifier (`contractguard-evidence.json` and `contractguard-report.md`).

---

## Limitations

ContractGuard maintains strict boundaries and does not claim more than its implementation proves:
- **OpenAPI REST Contracts**: Analyzes OpenAPI 3.x specifications; non-REST protocols (AsyncAPI, GraphQL, gRPC) are not supported in Phase 2.
- **Local Git CLI Subprocess**: Operates through the host `git` executable without remote network calls or GitHub/GitLab token authentication.
- **Shared Workspace Assumption**: Assumes consumer and producer service repositories reside within a shared workspace tree or accessible filesystem.
- **Contract-Bound Detection**: Scans contract specifications and token occurrences in code; purely internal code refactors without OpenAPI contract modifications cannot be detected statically via schema diffs alone.
- **Deferred Phase 3 Features**: Event-driven contracts, centralized schema registries, automated DTO code generation, and direct PR commenting bots remain deferred.

---

## Testing

Run the comprehensive test suite (118 passing tests, completely independent of external network or API keys):

```bash
pytest
```

Run with test coverage report:
```bash
pytest --cov=contract_guard --cov-report=term-missing
```

Phase 2 maintains 100% test passing rate and 80% code coverage across all modules.
