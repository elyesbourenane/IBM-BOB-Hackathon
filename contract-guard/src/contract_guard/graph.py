"""
Deterministic dependency graph module for ContractGuard Phase 3B.

Represents explicit producer-consumer contract relationships declared in
contractguard.yaml configurations across the workspace.

Guiding Principles:
- Strictly deterministic: no heuristics, no LLM inferences, no guessing.
- Built solely from authoritative declarations (contractguard.yaml, OpenAPI contracts).
- Clear separation between direct consumers and multi-hop transitive consumers.
- Deterministically sorted nodes, edges, and contract lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import load_config, ContractGuardConfig
from .discovery import _find_config_files


@dataclass
class DependencyNode:
    """Represents a service node in the contract dependency graph."""

    service: str
    repository: str
    contracts: list[str] = field(default_factory=list)
    is_producer: bool = False
    is_consumer: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "repository": self.repository,
            "contracts": sorted(list(dict.fromkeys(self.contracts))),
            "is_producer": self.is_producer,
            "is_consumer": self.is_consumer,
        }


@dataclass
class DependencyEdge:
    """Represents a directional producer -> consumer contract dependency."""

    producer: str
    consumer: str
    contract: str
    relationship_type: str = "direct_consumer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer": self.producer,
            "consumer": self.consumer,
            "contract": self.contract,
            "relationship_type": self.relationship_type,
        }


@dataclass
class DependencyGraph:
    """Deterministic, queryable representation of the service contract topology."""

    nodes: list[DependencyNode] = field(default_factory=list)
    edges: list[DependencyEdge] = field(default_factory=list)

    def get_direct_consumers(self, producer: str) -> list[str]:
        """Return deterministically sorted list of direct consumer services for *producer*."""
        consumers = {e.consumer for e in self.edges if e.producer == producer}
        return sorted(consumers)

    def get_transitive_consumers(self, producer: str) -> list[str]:
        """
        Return deterministically sorted list of multi-hop transitive consumers for *producer*.

        Only consumers reachable via chained explicit edges (A -> B -> C) that are
        NOT direct consumers of *producer* are returned.
        If no explicit downstream multi-hop edges exist, returns an empty list [].
        """
        direct = set(self.get_direct_consumers(producer))
        visited: set[str] = set()
        queue: list[str] = list(direct)

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            # Find downstream consumers of curr
            downstream = {e.consumer for e in self.edges if e.producer == curr}
            for d in downstream:
                if d not in visited and d != producer:
                    queue.append(d)

        # Transitive consumers are those reached that are not direct consumers
        transitive = visited - direct
        return sorted(transitive)

    def get_producers(self, consumer: str) -> list[str]:
        """Return deterministically sorted list of producer services that *consumer* depends on."""
        producers = {e.producer for e in self.edges if e.consumer == consumer}
        return sorted(producers)

    def render_tree(self, root_service: Optional[str] = None) -> str:
        """Render a deterministic ASCII tree of the dependency graph."""
        lines: list[str] = []
        if root_service:
            roots = [root_service]
        else:
            # Producers that are not consumers or all producers
            producers = sorted(list(dict.fromkeys(e.producer for e in self.edges)))
            roots = producers if producers else sorted(list(dict.fromkeys(n.service for n in self.nodes)))

        for root in roots:
            lines.append(root)
            direct = self.get_direct_consumers(root)
            for i, c in enumerate(direct):
                is_last_direct = (i == len(direct) - 1)
                prefix = "+-- " if not is_last_direct else "+-- "
                lines.append(f"    {prefix}{c}")
                # Transitive consumers under c
                transitive = self.get_direct_consumers(c)
                for j, tc in enumerate(transitive):
                    lines.append(f"        +-- {tc}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in sorted(self.nodes, key=lambda x: x.service)],
            "edges": [
                e.to_dict()
                for e in sorted(
                    self.edges,
                    key=lambda x: (x.producer, x.consumer, x.contract, x.relationship_type),
                )
            ],
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def build_dependency_graph(
    workspace_root: str | Path,
    producer_filter: Optional[str] = None,
) -> DependencyGraph:
    """
    Construct a deterministic DependencyGraph from all contractguard.yaml files in *workspace_root*.

    Does NOT guess or infer relationships from directories, packages, or code imports.
    Only explicit contract configurations are included.
    """
    ws = Path(workspace_root).resolve()
    if not ws.exists() or not ws.is_dir():
        return DependencyGraph()

    config_paths = _find_config_files(ws)
    nodes_by_service: dict[str, DependencyNode] = {}
    edges_set: set[tuple[str, str, str, str]] = set()

    for cp in config_paths:
        try:
            cfg = load_config(cp)
        except Exception:
            continue

        consumer_svc = cfg.service
        try:
            repo_rel = str(cfg.base_dir.resolve().relative_to(ws)).replace("\\", "/")
        except ValueError:
            repo_rel = str(cfg.base_dir).replace("\\", "/")

        if not repo_rel:
            repo_rel = "."

        # Register or update consumer node
        if consumer_svc not in nodes_by_service:
            nodes_by_service[consumer_svc] = DependencyNode(
                service=consumer_svc,
                repository=repo_rel,
                contracts=[],
                is_producer=False,
                is_consumer=True,
            )
        else:
            nodes_by_service[consumer_svc].is_consumer = True
            if not nodes_by_service[consumer_svc].repository or nodes_by_service[consumer_svc].repository == ".":
                nodes_by_service[consumer_svc].repository = repo_rel

        for dep in cfg.dependencies:
            prod_svc = dep.service
            if producer_filter and prod_svc != producer_filter:
                continue

            # Register producer node if not yet registered
            if prod_svc not in nodes_by_service:
                # Deduce producer repository if contract path points inside workspace
                prod_repo = prod_svc
                if dep.producer_contract.exists():
                    try:
                        p_rel = dep.producer_contract.resolve().relative_to(ws)
                        prod_repo = p_rel.parts[0] if p_rel.parts else prod_svc
                    except ValueError:
                        prod_repo = prod_svc

                nodes_by_service[prod_svc] = DependencyNode(
                    service=prod_svc,
                    repository=prod_repo,
                    contracts=[],
                    is_producer=True,
                    is_consumer=False,
                )
            else:
                nodes_by_service[prod_svc].is_producer = True

            # Record contracts
            c_contract_str = ""
            if dep.consumer_contract:
                try:
                    c_contract_str = str(dep.consumer_contract.resolve().relative_to(ws)).replace("\\", "/")
                except ValueError:
                    c_contract_str = str(dep.consumer_contract).replace("\\", "/")
                if c_contract_str not in nodes_by_service[consumer_svc].contracts:
                    nodes_by_service[consumer_svc].contracts.append(c_contract_str)

            p_contract_str = ""
            if dep.producer_contract:
                try:
                    p_contract_str = str(dep.producer_contract.resolve().relative_to(ws)).replace("\\", "/")
                except ValueError:
                    p_contract_str = str(dep.producer_contract).replace("\\", "/")
                if p_contract_str not in nodes_by_service[prod_svc].contracts:
                    nodes_by_service[prod_svc].contracts.append(p_contract_str)

            contract_ref = c_contract_str or p_contract_str or "contract"
            edge_key = (prod_svc, consumer_svc, contract_ref, "direct_consumer")
            edges_set.add(edge_key)

    # Deterministic sorting
    sorted_nodes = sorted(nodes_by_service.values(), key=lambda n: n.service)
    for n in sorted_nodes:
        n.contracts.sort()

    sorted_edges = [
        DependencyEdge(
            producer=e[0],
            consumer=e[1],
            contract=e[2],
            relationship_type=e[3],
        )
        for e in sorted(edges_set, key=lambda x: (x[0], x[1], x[2], x[3]))
    ]

    return DependencyGraph(nodes=sorted_nodes, edges=sorted_edges)
