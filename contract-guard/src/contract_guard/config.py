"""
Load and validate a ``contractguard.yaml`` consumer configuration file.

Schema
------
.. code-block:: yaml

    service: payment-client

    dependencies:
      - service: payment-service
        consumer_contract: contracts/payment-service.yaml
        producer_contract: ../payment-service/docs/openapi.yaml

Both ``consumer_contract`` and ``producer_contract`` are resolved relative to
the directory that contains the ``contractguard.yaml`` file, so the paths stay
meaningful regardless of the working directory the tool is invoked from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DependencyConfig:
    """One entry in the ``dependencies`` list."""

    service: str
    consumer_contract: Path
    producer_contract: Path


@dataclass
class ContractGuardConfig:
    """Parsed contents of a ``contractguard.yaml`` file."""

    service: str
    dependencies: list[DependencyConfig] = field(default_factory=list)
    #: Directory containing the config file — used as the resolution base.
    base_dir: Path = field(default_factory=Path)


def load_config(config_path: str | Path) -> ContractGuardConfig:
    """
    Parse a ``contractguard.yaml`` file and return a :class:`ContractGuardConfig`.

    All relative paths inside the file are resolved against the directory that
    contains the config file, so callers always get absolute ``Path`` objects
    for ``consumer_contract`` and ``producer_contract``.

    Raises
    ------
    FileNotFoundError
        If *config_path* does not exist.
    ValueError
        If the file is malformed or missing required fields.
    """
    config_path = Path(config_path).resolve()
    base_dir = config_path.parent

    with open(config_path, encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"contractguard.yaml must be a YAML mapping: {config_path}")

    service = raw.get("service")
    if not service:
        raise ValueError(f"contractguard.yaml missing required field 'service': {config_path}")

    raw_deps = raw.get("dependencies") or []
    if not isinstance(raw_deps, list):
        raise ValueError(f"'dependencies' must be a list: {config_path}")

    dependencies: list[DependencyConfig] = []
    for i, dep in enumerate(raw_deps):
        if not isinstance(dep, dict):
            raise ValueError(f"dependencies[{i}] must be a mapping: {config_path}")
        for key in ("service", "consumer_contract", "producer_contract"):
            if not dep.get(key):
                raise ValueError(
                    f"dependencies[{i}] missing required field '{key}': {config_path}"
                )
        dependencies.append(
            DependencyConfig(
                service=dep["service"],
                consumer_contract=(base_dir / dep["consumer_contract"]).resolve(),
                producer_contract=(base_dir / dep["producer_contract"]).resolve(),
            )
        )

    return ContractGuardConfig(
        service=service,
        dependencies=dependencies,
        base_dir=base_dir,
    )
