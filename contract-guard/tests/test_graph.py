"""Tests for ContractGuard Phase 3B deterministic dependency graph."""

from __future__ import annotations

import json
from pathlib import Path

from contract_guard.graph import (
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    build_dependency_graph,
)


def test_dependency_node_and_edge_models():
    node = DependencyNode(
        service="payment-service",
        repository="payment-service",
        contracts=["docs/openapi.yaml", "docs/openapi.yaml"],
        is_producer=True,
    )
    d = node.to_dict()
    assert d["service"] == "payment-service"
    assert d["repository"] == "payment-service"
    # Contracts are deduplicated and sorted
    assert d["contracts"] == ["docs/openapi.yaml"]
    assert d["is_producer"] is True
    assert d["is_consumer"] is False

    edge = DependencyEdge(
        producer="payment-service",
        consumer="payment-client",
        contract="contracts/payment-service.yaml",
    )
    ed = edge.to_dict()
    assert ed["producer"] == "payment-service"
    assert ed["consumer"] == "payment-client"
    assert ed["relationship_type"] == "direct_consumer"


def test_graph_construction_and_direct_consumers(tmp_path: Path):
    # Setup workspace: payment-service producer and 3 consumers
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Producer
    prod_dir = ws / "payment-service" / "docs"
    prod_dir.mkdir(parents=True)
    (prod_dir / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")

    # Consumers
    consumers = ["reporting-service", "order-service", "payment-client"]
    for c in consumers:
        c_dir = ws / c
        (c_dir / "contracts").mkdir(parents=True)
        (c_dir / "contracts" / "payment-service.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
        (c_dir / "contractguard.yaml").write_text(
            f"service: {c}\ndependencies:\n  - service: payment-service\n    consumer_contract: contracts/payment-service.yaml\n    producer_contract: ../payment-service/docs/openapi.yaml\n",
            encoding="utf-8",
        )

    graph = build_dependency_graph(ws)

    # Deterministic node ordering
    node_services = [n.service for n in graph.nodes]
    assert node_services == ["order-service", "payment-client", "payment-service", "reporting-service"]

    # Direct consumers of payment-service
    direct = graph.get_direct_consumers("payment-service")
    assert direct == ["order-service", "payment-client", "reporting-service"]

    # Transitive consumers of payment-service (none exist in this flat topology)
    transitive = graph.get_transitive_consumers("payment-service")
    assert transitive == []


def test_graph_deterministic_edge_ordering_and_deduplication(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Two consumer configs pointing to the same producer contract
    c1 = ws / "consumer-b"
    c1.mkdir()
    (c1 / "contract.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (c1 / "contractguard.yaml").write_text(
        "service: consumer-b\ndependencies:\n  - service: producer-a\n    consumer_contract: contract.yaml\n    producer_contract: contract.yaml\n  - service: producer-a\n    consumer_contract: contract.yaml\n    producer_contract: contract.yaml\n",
        encoding="utf-8",
    )

    c2 = ws / "consumer-a"
    c2.mkdir()
    (c2 / "contract.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (c2 / "contractguard.yaml").write_text(
        "service: consumer-a\ndependencies:\n  - service: producer-a\n    consumer_contract: contract.yaml\n    producer_contract: contract.yaml\n",
        encoding="utf-8",
    )

    graph = build_dependency_graph(ws)

    # Edge deduplication: only 2 unique edges
    assert len(graph.edges) == 2
    # Deterministic edge sorting: consumer-a comes before consumer-b
    assert graph.edges[0].consumer == "consumer-a"
    assert graph.edges[1].consumer == "consumer-b"


def test_graph_transitive_consumers(tmp_path: Path):
    # Setup chained dependency: service-a -> service-b -> service-c
    ws = tmp_path / "workspace"
    ws.mkdir()

    sa = ws / "service-a"
    sa.mkdir()
    (sa / "contract.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")

    sb = ws / "service-b"
    sb.mkdir()
    (sb / "contract.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (sb / "contractguard.yaml").write_text(
        "service: service-b\ndependencies:\n  - service: service-a\n    consumer_contract: contract.yaml\n    producer_contract: ../service-a/contract.yaml\n",
        encoding="utf-8",
    )

    sc = ws / "service-c"
    sc.mkdir()
    (sc / "contract.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (sc / "contractguard.yaml").write_text(
        "service: service-c\ndependencies:\n  - service: service-b\n    consumer_contract: contract.yaml\n    producer_contract: ../service-b/contract.yaml\n",
        encoding="utf-8",
    )

    graph = build_dependency_graph(ws)

    # Direct consumers of service-a
    assert graph.get_direct_consumers("service-a") == ["service-b"]
    # Transitive consumers of service-a
    assert graph.get_transitive_consumers("service-a") == ["service-c"]

    # Direct consumers of service-b
    assert graph.get_direct_consumers("service-b") == ["service-c"]
    assert graph.get_transitive_consumers("service-b") == []


def test_graph_render_tree_and_json(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    # service-a -> service-b
    sa = ws / "service-a"
    sa.mkdir()
    (sa / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")

    sb = ws / "service-b"
    sb.mkdir()
    (sb / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (sb / "contractguard.yaml").write_text(
        "service: service-b\ndependencies:\n  - service: service-a\n    consumer_contract: openapi.yaml\n    producer_contract: ../service-a/openapi.yaml\n",
        encoding="utf-8",
    )

    graph = build_dependency_graph(ws)
    tree = graph.render_tree("service-a")
    assert "service-a" in tree
    assert "+-- service-b" in tree

    d = graph.to_dict()
    assert d["total_nodes"] == 2
    assert d["total_edges"] == 1
    j = graph.to_json()
    parsed = json.loads(j)
    assert parsed["total_nodes"] == 2
