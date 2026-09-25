# contract-guard

A **deterministic** OpenAPI contract compatibility checker. Compare a producer OpenAPI YAML contract against a consumer OpenAPI YAML contract and get a clear, rule-based verdict — no AI, no guesswork.

Exposes a **CLI** for local use and an **MCP server** so AI coding agents like IBM Bob can call it automatically during development workflows.

---

## Features

| Rule | Severity |
|---|---|
| Field removed from producer response | **Breaking** |
| Field renamed / replaced in producer response | **Breaking** |
| Field type changed | **Breaking** |
| Optional field made required | **Breaking** |
| New optional field added | Compatible |

---

## Requirements

- Python 3.9+
- [PyYAML](https://pyyaml.org/) (only runtime dependency)

---

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd contract-guard

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS / Linux

# Install in editable mode
pip install -e .

# Install with dev extras (pytest)
pip install -e ".[dev]"
```

---

## CLI usage

```bash
python -m contract_guard compare <producer.yaml> <consumer.yaml>
```

### Demo scenario

The `contracts/` directory contains a ready-made example where the producer renamed `amount` → `paymentAmount`:

```bash
python -m contract_guard compare contracts/producer.yaml contracts/consumer.yaml --no-color
```

Expected output:

```
[!!] BREAKING

Breaking changes:
  Endpoint    : GET /api/payments/{id}
  Field       : amount
  Change      : field_renamed
  Detail      : Consumer expects 'amount' but producer now uses 'paymentAmount' (same type 'number').
  Reason      : Consumer expects the old field name; renaming it is equivalent to removal.
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All changes are compatible |
| `1` | At least one breaking change detected |
| `2` | Input error (file not found, invalid YAML, etc.) |

### Options

```
--no-color    Disable ANSI colour output (useful for CI logs)
```

---

## Running tests

```bash
pytest
# With coverage
pytest --cov=contract_guard --cov-report=term-missing
```

---

## MCP server

`contract-guard` ships a built-in MCP stdio server. When registered with IBM Bob, it exposes the
`compare_contracts` tool so Bob can check contract compatibility automatically — for example,
when you ask it to review an API change or generate a compatibility report.

### What the tool does

**Tool name:** `compare_contracts`

**Inputs:**
| Parameter | Type | Description |
|---|---|---|
| `producer_path` | string | Absolute path to the producer OpenAPI YAML file |
| `consumer_path` | string | Absolute path to the consumer OpenAPI YAML file |

**Output:** a JSON object with:
```jsonc
{
  "verdict": "breaking",          // "breaking" or "compatible"
  "is_compatible": false,
  "breaking_count": 1,
  "compatible_count": 0,
  "findings": [
    {
      "endpoint": "GET /api/payments/{id}",
      "affected_field": "amount",
      "change_kind": "field_renamed",
      "severity": "breaking",
      "detail": "Consumer expects 'amount' but producer now uses 'paymentAmount' (same type 'number').",
      "reason": "Consumer expects the old field name; renaming it is equivalent to removal."
    }
  ]
}
```

### Connecting to IBM Bob

#### Step 1 — find the Python executable path

The server is a Python stdio process. You need the absolute path to the Python interpreter that
has `contract-guard` installed.

```bash
# Windows (PowerShell)
(Get-Command python).Source

# macOS / Linux
which python
# or, if using a venv:
which .venv/bin/python
```

#### Step 2 — register in Bob's MCP config

Open **Bob → Settings → MCP Servers** and add a new entry, or edit `mcp.json` directly.

**Workspace-scoped** (`<your-project>/.bob/mcp.json`):

```json
{
  "mcpServers": {
    "contract-guard": {
      "command": "C:/path/to/python",
      "args": ["-m", "contract_guard.mcp_server"]
    }
  }
}
```

**Globally-scoped** (`%APPDATA%\Bob\mcp.json` on Windows, `~/.config/bob/mcp.json` on Linux/macOS):

```json
{
  "mcpServers": {
    "contract-guard": {
      "command": "/path/to/python",
      "args": ["-m", "contract_guard.mcp_server"]
    }
  }
}
```

> **Note:** use the Python interpreter from the virtualenv where `contract-guard` is installed,
> not the system Python, unless you installed it globally.

> **Windows note:** use forward slashes or escaped backslashes in the path:
> `"C:/Users/you/.venv/Scripts/python.exe"` or `"C:\\Users\\you\\.venv\\Scripts\\python.exe"`.

#### Step 3 — verify the connection

After saving, Bob hot-reloads the server. You should see **contract-guard** appear as connected
in Bob's MCP panel. You can then ask Bob:

> "Check whether `contracts/producer.yaml` is compatible with `contracts/consumer.yaml`"

Bob will call `compare_contracts` with the resolved absolute paths and return the structured report.

### Running the server manually (for debugging)

```bash
# Start the server — it listens on stdin and replies on stdout
python -m contract_guard.mcp_server

# Feed a raw JSON-RPC exchange (one message per line):
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"0"},"capabilities":{}}}' | python -m contract_guard.mcp_server
```

All server-side diagnostics go to **stderr**, not stdout, so they never corrupt the protocol channel.

---

## Project structure

```
contract-guard/
├── contracts/
│   ├── producer.yaml        # Demo producer contract (v2, uses paymentAmount)
│   └── consumer.yaml        # Demo consumer contract (v1, expects amount)
├── src/
│   └── contract_guard/
│       ├── __init__.py
│       ├── __main__.py      # CLI entry point
│       ├── mcp_server.py    # MCP stdio server (JSON-RPC 2.0, no extra deps)
│       ├── models.py        # Data classes: Finding, ComparisonReport
│       ├── loader.py        # YAML loading + $ref resolution
│       ├── extractor.py     # OpenAPI -> flat property map
│       ├── rules.py         # Pure compatibility rule functions
│       └── comparator.py    # Orchestrates loading + rules
├── tests/
│   ├── test_rules.py        # Unit tests for each rule
│   └── test_comparator.py  # Integration tests using temp YAML files
├── pyproject.toml
└── README.md
```

---

## Architecture decisions

- **Deterministic rules only** — every verdict is traceable to a specific rule function in `rules.py`.
- **Rename heuristic** — when a consumer field is absent from the producer but a producer field of the same type is absent from the consumer (with no ambiguity), it is classified as a rename rather than an independent removal + addition. This keeps noise low.
- **Flat property map** — `extractor.flatten_properties()` walks nested object schemas and produces a dot-separated field path map, making rule functions simple key-set operations.
- **Minimal dependencies** — only PyYAML at runtime; zero extra deps for the MCP server (raw JSON-RPC 2.0 over stdio).
- **Thin MCP layer** — `mcp_server.py` is a pure protocol adapter. It calls `Comparator.compare()` and serialises the result. No AI logic lives here.
