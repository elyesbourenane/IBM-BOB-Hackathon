# ContractGuard — Consumer Compatibility

When modifying a **producer API contract** (e.g. `openapi.yaml`, `docs/openapi.yaml`) or an **API response model** (e.g. a DTO/response class whose fields are serialised to JSON), consider whether downstream consumers may be affected before finalising the change.

## When to apply this rule

Apply this rule when the change involves any of the following in a producer service:

- Renaming, removing, or changing the type of a response field
- Removing or renaming an endpoint
- Making a previously optional response field required
- Any other modification to a published response schema

This rule does **not** apply to internal refactors, request validation changes, non-API code, or consumer-side changes.

## Preferred workflow

1. **Identify the affected producer** — note the service name and the OpenAPI contract path.
2. **Run ContractGuard** — call `discover_and_check_consumers` with `workspace_root` set to the workspace directory and `producer_filter` set to the producer service name.
3. **Inspect breaking consumers** — if affected consumers are reported, read their consumer contract and relevant source files to understand what needs to change.
4. **Apply fixes when asked** — only update consumer contracts and client code if the user explicitly requests it; never modify consumers silently.
5. **Run consumer tests** — after updating a consumer, run its test suite to confirm the fix is correct.
6. **Re-run ContractGuard** — call `discover_and_check_consumers` again to confirm all consumers show `compatible`.

## Notes

- The ContractGuard MCP tools are `discover_and_check_consumers` (workspace-wide scan), `read_contractguard_config` (single config), and `compare_contracts` (single pair).
- Always pass the explicit absolute or workspace-relative path to `workspace_root`; the default may resolve incorrectly.
- Do not modify the ContractGuard engine (`contract-guard/` directory).
- Consumer contracts live in each consumer's `contracts/` directory and are the source of truth for compatibility checks.
