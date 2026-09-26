"""High-level comparator: orchestrates loading, extraction, and rule evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .extractor import flatten_properties, get_response_schema, iter_endpoints
from .loader import load_contract
from .models import ChangeKind, ComparisonReport, Finding
from .rules import ALL_RULES, _detect_renames


class Comparator:
    """Compare a producer contract against a consumer contract."""

    def __init__(
        self,
        producer_path: str | Path,
        consumer_path: str | Path,
    ) -> None:
        self.producer_path = Path(producer_path)
        self.consumer_path = Path(consumer_path)

    def compare(self) -> ComparisonReport:
        producer_doc = load_contract(self.producer_path)
        consumer_doc = load_contract(self.consumer_path)
        return self._compare_docs(producer_doc, consumer_doc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compare_docs(
        self,
        producer_doc: dict[str, Any],
        consumer_doc: dict[str, Any],
    ) -> ComparisonReport:
        report = ComparisonReport()

        producer_endpoints = {
            f"{method} {path}": op
            for method, path, op in iter_endpoints(producer_doc)
        }
        consumer_endpoints = {
            f"{method} {path}": op
            for method, path, op in iter_endpoints(consumer_doc)
        }

        for endpoint_key, consumer_op in sorted(consumer_endpoints.items()):
            producer_op = producer_endpoints.get(endpoint_key)
            if producer_op is None:
                report.findings.append(
                    Finding(
                        endpoint=endpoint_key,
                        affected_field="",
                        change_kind=ChangeKind.ENDPOINT_REMOVED,
                        detail=(
                            f"Endpoint '{endpoint_key}' is expected by consumer "
                            f"but is not present in producer specification."
                        ),
                    )
                )
                continue

            findings = self._compare_responses(
                endpoint_key, producer_op, producer_doc, consumer_op, consumer_doc
            )
            report.findings.extend(findings)

        report.findings.sort(key=lambda f: (f.endpoint, f.affected_field, f.change_kind.value))
        return report

    def _compare_responses(
        self,
        endpoint: str,
        producer_op: dict[str, Any],
        producer_doc: dict[str, Any],
        consumer_op: dict[str, Any],
        consumer_doc: dict[str, Any],
    ) -> list[Finding]:
        producer_schema = get_response_schema(producer_op, producer_doc)
        consumer_schema = get_response_schema(consumer_op, consumer_doc)

        if producer_schema is None or consumer_schema is None:
            return []

        producer_props = flatten_properties(producer_schema, producer_doc)
        consumer_props = flatten_properties(consumer_schema, consumer_doc)

        # Run rename detection first; exclude renamed fields from other rules
        rename_findings, renamed_consumer, renamed_producer = _detect_renames(
            producer_props, consumer_props, endpoint
        )

        # Narrow views that exclude already-explained rename pairs
        effective_producer = {
            k: v for k, v in producer_props.items() if k not in renamed_producer
        }
        effective_consumer = {
            k: v for k, v in consumer_props.items() if k not in renamed_consumer
        }

        findings: list[Finding] = list(rename_findings)
        for rule in ALL_RULES:
            findings.extend(rule(effective_producer, effective_consumer, endpoint))

        return findings
